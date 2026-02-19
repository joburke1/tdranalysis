"""
Anomaly Detection for TDR Analysis Results
===========================================

Detects data quality issues and statistical outliers in analysis output,
then classifies each parcel into one of three tiers:

  auto-exclude    — parcel has a disqualifying data quality problem that makes
                    including it in the analysis indefensible.  Opponents could
                    trivially challenge these records.

  flag-for-review — parcel has a potential issue that warrants human review
                    before trusting the analysis result.  Conservative approach:
                    these parcels are still included in the "full" analysis but
                    excluded from the "conservative" (clean-only) analysis.

  clean           — parcel passes all checks; no detected issues.

Design principles
-----------------
- Operates on the flat CSV output of run_analysis.py (a pandas DataFrame),
  not on the raw GeoDataFrame.  This allows independent verification without
  re-running the full pipeline.
- Rules are intentionally conservative: we prefer false positives (over-
  flagging) to false negatives (missing real problems).
- All flags are accumulated; a parcel may carry multiple flags.
- Thresholds are documented with rationale so they can be tuned as the
  analysis is extended to other neighborhoods.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Non-residential property class code prefixes
# ---------------------------------------------------------------------------
# The Arlington County property API uses a 3-digit prefix for the class code.
# Codes in the 100-299 range are generally commercial/industrial; 300-399 are
# multi-family / apartment; 500-599 are residential.  We flag anything outside
# the residential 500-599 range plus a few known problematic codes.
#
# "Auto-exclude" codes: clearly non-single-family-residential use
_AUTO_EXCLUDE_CLASS_PREFIXES = {
    "200",  # GenCom VacLand-no siteplan
    "201",  # GenCom VacLand-siteplan
    "210",  # Gen Comm Parking
    "215",  # Gen Comm - other
    "220",  # Office
    "300",  # Industrial / Apartment Parking
    "310",  # Apartment Parking
}

# "Flag" codes: may be legitimate in context but deserve a second look
_FLAG_CLASS_PREFIXES = {
    "540",  # Not Valued Resd. (H.O.A.) — common areas, not individual lots
}

# Residential class codes that are normal / expected
_RESIDENTIAL_CLASS_PREFIXES = {
    "510",  # Res - Vacant (SF & Twnhse)
    "511",  # Single Family Detached
    "512",  # Townhouse (fee simple own)
    "513",  # Townhouse (condo own)
    "514",  # Side by side (duplex)
    "515",  # Duplex
    "516",  # Semi-detached
}

# ---------------------------------------------------------------------------
# Thresholds (documented with rationale)
# ---------------------------------------------------------------------------

# Minimum lot area below which the parcel is likely a remnant strip / alley,
# not a buildable lot regardless of zoning district.  No residential unit can
# realistically be constructed on a 1000 SF parcel in Arlington.
LOT_AREA_REMNANT_SF = 1_000.0

# Minimum lot area to consider "potentially buildable" without flagging.
# Below this the parcel may be technically in the system but not economically
# or physically developable (no garage fits in 20 ft × 100 ft).
LOT_AREA_MARGINAL_SF = 2_000.0

# Minimum lot width.  Arlington's narrowest residential districts (R2-7) have
# a 40 ft minimum frontage.  Below 15 ft the lot is almost certainly a shared
# driveway remnant or similar.
LOT_WIDTH_REMNANT_FT = 15.0

# Improvement value below which the GFA-from-improvement-value estimate is
# unreliable.  At $185/SF this translates to ~160 SF of estimated floor area —
# far too little to be a meaningful residential building.
IMPROVEMENT_VALUE_UNRELIABLE = 30_000.0

# Z-score threshold for flagging statistical outliers within a zoning district.
# Z > 2.5 means the value is more than 2.5 standard deviations from the
# district mean — unusual enough to warrant a check.
ZSCORE_THRESHOLD = 2.5


# ---------------------------------------------------------------------------
# Named tuple for detection results
# ---------------------------------------------------------------------------

class AnomalyResult(NamedTuple):
    """Anomaly detection result for a single parcel."""
    parcel_id: str
    quality_tier: str          # "auto-exclude", "flag-for-review", or "clean"
    anomaly_flags: list[str]   # list of specific flag codes
    anomaly_count: int         # number of flags


# ---------------------------------------------------------------------------
# Individual detection functions
# ---------------------------------------------------------------------------

def _flag_nonresidential_type(row: pd.Series) -> list[str]:
    """Flag non-residential property type codes in a residential zone."""
    flags: list[str] = []
    ptype = str(row.get("property_type", "") or "")
    prefix = ptype[:3]

    if prefix in _AUTO_EXCLUDE_CLASS_PREFIXES:
        flags.append(f"nonresidential_property_type:{ptype.strip()}")
    elif prefix in _FLAG_CLASS_PREFIXES:
        flags.append(f"unusual_property_type:{ptype.strip()}")
    elif prefix not in _RESIDENTIAL_CLASS_PREFIXES and ptype and ptype != "nan":
        # Unknown / unclassified property type — flag for review
        flags.append(f"unknown_property_type:{ptype.strip()}")

    return flags


def _flag_lot_geometry(row: pd.Series) -> list[str]:
    """Flag geometric anomalies: very small or very narrow lots."""
    flags: list[str] = []

    lot_area = row.get("lot_area_sf")
    lot_width = row.get("lot_width_ft")

    if pd.notna(lot_area):
        if lot_area < LOT_AREA_REMNANT_SF:
            flags.append(f"lot_area_remnant:{lot_area:.0f}sf<{LOT_AREA_REMNANT_SF:.0f}sf_threshold")
        elif lot_area < LOT_AREA_MARGINAL_SF:
            flags.append(f"lot_area_marginal:{lot_area:.0f}sf<{LOT_AREA_MARGINAL_SF:.0f}sf_threshold")

    if pd.notna(lot_width):
        if lot_width < LOT_WIDTH_REMNANT_FT:
            flags.append(f"lot_width_remnant:{lot_width:.1f}ft<{LOT_WIDTH_REMNANT_FT:.0f}ft_threshold")

    return flags


def _flag_dwelling_unit_inconsistency(row: pd.Series) -> list[str]:
    """Flag the logical inconsistency: max_dwelling_units=0 but available_gfa_sf > 0."""
    flags: list[str] = []

    max_du = row.get("max_dwelling_units")
    avail_gfa = row.get("available_gfa_sf")

    if pd.notna(max_du) and pd.notna(avail_gfa):
        if int(max_du) == 0 and float(avail_gfa) > 0:
            flags.append(
                f"dwelling_unit_inconsistency:max_du=0_but_available_gfa={avail_gfa:.0f}sf"
            )

    return flags


def _flag_split_zoning(row: pd.Series) -> list[str]:
    """Split-zoned parcels are not flagged.

    Review of Alcova Heights split-zoned parcels confirmed they are all
    residential lots that happen to border other zoning districts.  The
    analysis already applies the primary zone's rules, so split-zoning
    does not affect result accuracy.  Retained as a no-op so the function
    can be re-enabled for other neighborhoods if needed.
    """
    return []


def _flag_gfa_estimation_quality(row: pd.Series) -> list[str]:
    """Flag parcels where the GFA estimate is likely unreliable."""
    flags: list[str] = []

    gfa_source = str(row.get("gfa_source", "") or "")
    imp_value = row.get("improvement_value")

    if "improvement_value" in gfa_source:
        if pd.notna(imp_value) and float(imp_value) < IMPROVEMENT_VALUE_UNRELIABLE:
            flags.append(
                f"low_improvement_value:${imp_value:.0f}<${IMPROVEMENT_VALUE_UNRELIABLE:.0f}_makes_gfa_estimate_unreliable"
            )
        elif pd.notna(imp_value) and float(imp_value) == 0:
            flags.append("zero_improvement_value:gfa_estimate_is_zero_divided_by_rate")

    if gfa_source == "building_detected_no_gfa_data":
        flags.append("building_detected_no_gfa_data:available_rights_not_computed")

    if gfa_source == "not_available":
        # Vacant parcels have no GFA by definition — not a data quality issue.
        dev_status = str(row.get("development_status", "") or "")
        if dev_status != "vacant":
            flags.append("gfa_not_available:no_property_data_for_gfa")

    return flags


def _flag_overdeveloped_with_valuation(row: pd.Series) -> list[str]:
    """Flag overdeveloped parcels that somehow received a positive valuation."""
    flags: list[str] = []

    avail_gfa = row.get("available_gfa_sf")
    est_low = row.get("est_value_low")

    if pd.notna(avail_gfa) and float(avail_gfa) < 0 and pd.notna(est_low) and float(est_low) > 0:
        flags.append(
            f"overdeveloped_but_valued:available_gfa={avail_gfa:.0f}sf_but_est_value=${est_low:.0f}"
        )

    return flags


def _compute_zoning_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-zoning-district Z-scores for key numeric columns.

    Returns a DataFrame with the same index as df containing columns:
      z_lot_area_sf, z_available_gfa_sf, z_est_value_high
    """
    cols = ["lot_area_sf", "available_gfa_sf", "est_value_high"]
    z_df = pd.DataFrame(index=df.index)

    for col in cols:
        z_col = f"z_{col}"
        z_df[z_col] = np.nan
        if col not in df.columns:
            continue

        for district, group in df.groupby("zoning_district", dropna=False):
            vals = group[col].dropna()
            if len(vals) < 5:
                # Too few parcels to compute meaningful Z-scores
                continue
            mean = vals.mean()
            std = vals.std()
            if std == 0:
                continue
            z = (group[col] - mean) / std
            z_df.loc[group.index, z_col] = z.values

    return z_df


def _flag_statistical_outliers(row: pd.Series, z_row: pd.Series) -> list[str]:
    """Flag statistical outliers based on pre-computed per-district Z-scores."""
    flags: list[str] = []

    check_cols = {
        # lot_area_sf outliers (high side) are not data quality issues —
        # large lots are valid and often better TDR candidates.  Only flag
        # unusually SMALL lots (negative z-score) as those may indicate
        # remnant parcels that slipped through the size filter.
        # "z_lot_area_sf": "lot_area_sf",   # disabled: large lots are fine
        "z_available_gfa_sf": "available_gfa_sf",
        "z_est_value_high": "est_value_high",
    }

    for z_col, raw_col in check_cols.items():
        z_val = z_row.get(z_col)
        if pd.notna(z_val) and abs(float(z_val)) > ZSCORE_THRESHOLD:
            raw_val = row.get(raw_col)
            direction = "high" if float(z_val) > 0 else "low"
            flags.append(
                f"statistical_outlier:{raw_col}_z={z_val:.1f}_{direction}"
                + (f"_value={raw_val:.0f}" if pd.notna(raw_val) else "")
            )

    return flags


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

# These flag prefixes trigger auto-exclude (highest severity)
_AUTO_EXCLUDE_FLAG_PREFIXES = {
    "nonresidential_property_type:",
    "lot_area_remnant:",
    "lot_width_remnant:",
    "dwelling_unit_inconsistency:",
    "overdeveloped_but_valued:",
}


def classify_parcel_quality(
    row: pd.Series,
    z_row: pd.Series | None = None,
) -> tuple[str, list[str]]:
    """
    Classify a parcel's data quality and return tier + flags.

    Parameters
    ----------
    row : pd.Series
        A single row from the analysis CSV (one parcel).
    z_row : pd.Series, optional
        Pre-computed Z-score row for the same parcel.  If None, statistical
        outlier checks are skipped.

    Returns
    -------
    (quality_tier, anomaly_flags) where quality_tier is one of:
      "auto-exclude", "flag-for-review", "clean"
    """
    flags: list[str] = []

    flags.extend(_flag_nonresidential_type(row))
    flags.extend(_flag_lot_geometry(row))
    flags.extend(_flag_dwelling_unit_inconsistency(row))
    flags.extend(_flag_split_zoning(row))
    flags.extend(_flag_gfa_estimation_quality(row))
    flags.extend(_flag_overdeveloped_with_valuation(row))

    if z_row is not None:
        flags.extend(_flag_statistical_outliers(row, z_row))

    # Determine tier
    is_auto_exclude = any(
        any(flag.startswith(prefix) for prefix in _AUTO_EXCLUDE_FLAG_PREFIXES)
        for flag in flags
    )

    if is_auto_exclude:
        tier = "auto-exclude"
    elif flags:
        tier = "flag-for-review"
    else:
        tier = "clean"

    return tier, flags


# ---------------------------------------------------------------------------
# Bulk analysis on a DataFrame
# ---------------------------------------------------------------------------

def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run anomaly detection on the full analysis results DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        The analysis results CSV loaded into a DataFrame.  Must include at
        minimum: parcel_id, property_type, lot_area_sf, lot_width_ft,
        max_dwelling_units, available_gfa_sf, is_split_zoned, gfa_source,
        improvement_value, est_value_low, est_value_high, zoning_district.

    Returns
    -------
    pd.DataFrame with columns:
        parcel_id, quality_tier, anomaly_flags (pipe-separated string),
        anomaly_count
    Rows correspond 1-to-1 with input df rows (same index).
    """
    logger.info(f"Running anomaly detection on {len(df):,} parcels...")

    # Pre-compute per-district Z-scores once for the whole dataset
    z_df = _compute_zoning_zscores(df)

    results: list[dict] = []
    for idx, row in df.iterrows():
        z_row = z_df.loc[idx] if idx in z_df.index else None
        tier, flags = classify_parcel_quality(row, z_row)
        parcel_id = str(row.get("parcel_id", idx))
        results.append({
            "parcel_id": parcel_id,
            "quality_tier": tier,
            "anomaly_flags": "|".join(flags) if flags else "",
            "anomaly_count": len(flags),
        })

    out = pd.DataFrame(results, index=df.index)

    n_exclude = (out["quality_tier"] == "auto-exclude").sum()
    n_flag = (out["quality_tier"] == "flag-for-review").sum()
    n_clean = (out["quality_tier"] == "clean").sum()
    logger.info(
        f"  Results: {n_exclude} auto-exclude, {n_flag} flag-for-review, {n_clean} clean"
    )

    return out


def summarize_anomalies(df: pd.DataFrame, anomaly_df: pd.DataFrame) -> str:
    """
    Build a human-readable anomaly detection summary.

    Parameters
    ----------
    df : pd.DataFrame
        Original analysis results.
    anomaly_df : pd.DataFrame
        Output of detect_anomalies().

    Returns
    -------
    str : Formatted summary text.
    """
    lines = [
        "Anomaly Detection Report",
        "=" * 60,
        f"Total parcels analyzed: {len(df):,}",
        "",
    ]

    # Tier counts
    tier_counts = anomaly_df["quality_tier"].value_counts()
    lines.append("Quality Tier Summary:")
    for tier in ["auto-exclude", "flag-for-review", "clean"]:
        count = tier_counts.get(tier, 0)
        pct = count / len(df) * 100 if len(df) > 0 else 0
        lines.append(f"  {tier:<20} {count:>6,}  ({pct:.1f}%)")
    lines.append("")

    # Flag frequency
    all_flags: list[str] = []
    for flags_str in anomaly_df["anomaly_flags"].dropna():
        if flags_str:
            all_flags.extend(flags_str.split("|"))

    if all_flags:
        # Summarize by flag prefix (strip per-parcel values for readability)
        from collections import Counter
        flag_prefixes: list[str] = []
        for f in all_flags:
            # Keep text up to first colon (flag category), drop the value part
            prefix = f.split(":")[0]
            flag_prefixes.append(prefix)

        flag_counts = Counter(flag_prefixes)
        lines.append("Most common anomaly types:")
        for flag_prefix, count in flag_counts.most_common(15):
            lines.append(f"  {flag_prefix:<55} {count:>4,} parcel(s)")
        lines.append("")

    # Auto-exclude details
    auto_ex = anomaly_df[anomaly_df["quality_tier"] == "auto-exclude"]
    if len(auto_ex) > 0:
        lines.append(f"Auto-Exclude Parcels ({len(auto_ex)}):")
        merged = df.merge(
            auto_ex[["parcel_id", "anomaly_flags"]],
            on="parcel_id",
            how="inner",
        )
        for _, row in merged.iterrows():
            addr = row.get("street_address", "")
            flags = row.get("anomaly_flags", "")
            lines.append(f"  {row['parcel_id']:<12}  {addr:<45}  {flags}")
        lines.append("")

    # Flag-for-review details
    flag_rev = anomaly_df[anomaly_df["quality_tier"] == "flag-for-review"]
    if len(flag_rev) > 0:
        lines.append(f"Flag-for-Review Parcels ({len(flag_rev)}):")
        merged = df.merge(
            flag_rev[["parcel_id", "anomaly_flags"]],
            on="parcel_id",
            how="inner",
        )
        for _, row in merged.iterrows():
            addr = row.get("street_address", "")
            flags = row.get("anomaly_flags", "")
            lines.append(f"  {row['parcel_id']:<12}  {addr:<45}  {flags}")
        lines.append("")

    # Impact on aggregate values
    lines.append("Impact on Aggregate Values (available_gfa_sf and est_value_high):")
    merged_all = df.merge(anomaly_df[["parcel_id", "quality_tier"]], on="parcel_id", how="left")

    for tier in ["auto-exclude", "flag-for-review", "clean"]:
        sub = merged_all[merged_all["quality_tier"] == tier]
        gfa = sub["available_gfa_sf"].dropna()
        val = sub["est_value_high"].dropna()
        lines.append(
            f"  {tier:<20}  parcels={len(sub):>5,}  "
            f"total_avail_gfa={gfa[gfa>0].sum():>12,.0f} sf  "
            f"agg_value_high=${val.sum():>14,.0f}"
        )

    clean_sub = merged_all[merged_all["quality_tier"] == "clean"]
    clean_gfa = clean_sub["available_gfa_sf"].dropna()
    clean_val = clean_sub["est_value_high"].dropna()
    all_gfa = df["available_gfa_sf"].dropna()
    all_val = df["est_value_high"].dropna()

    if all_gfa[all_gfa > 0].sum() > 0:
        gfa_retention = clean_gfa[clean_gfa > 0].sum() / all_gfa[all_gfa > 0].sum() * 100
        lines.append(
            f"\n  Clean-tier GFA capacity as % of full analysis: {gfa_retention:.1f}%"
        )
    if all_val.sum() > 0:
        val_retention = clean_val.sum() / all_val.sum() * 100
        lines.append(
            f"  Clean-tier value as % of full analysis:        {val_retention:.1f}%"
        )

    lines.append("")
    lines.append("=" * 60)
    lines.append(
        "NOTE: 'auto-exclude' parcels have disqualifying data issues.\n"
        "      'flag-for-review' parcels warrant human review before\n"
        "      being included in final policy analysis.\n"
        "      'clean' parcels pass all automated checks."
    )

    return "\n".join(lines)
