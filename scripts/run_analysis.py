"""
Arlington Zoning Analyzer — Analysis Runner
============================================

Executes the full analysis pipeline for one or all civic association
neighborhoods in Arlington County, VA:

  1. Download GIS + property/assessment data (cached)
  2. Process: spatial join parcels → zoning + neighborhoods + property/assessment
  3. Filter to the requested neighborhood(s)
  4. Run analysis: development potential → current built → available rights → valuation
  5. Save results as GeoPackage + CSV and print a summary

Usage examples
--------------
# Verify environment first:
    python scripts/verify_env.py

# List available neighborhoods (after data is downloaded):
    python scripts/run_analysis.py --list-neighborhoods

# Run MVP: single neighborhood:
    python scripts/run_analysis.py --neighborhood "Lyon Park"

# Run all neighborhoods (batch mode):
    python scripts/run_analysis.py --all-neighborhoods

# Force re-download of source data before running:
    python scripts/run_analysis.py --neighborhood "Lyon Park" --force-refresh

# Check data freshness without running analysis:
    python scripts/run_analysis.py --check-data

# Use a custom data or output directory:
    python scripts/run_analysis.py --neighborhood "Lyon Park" \\
        --data-dir data/raw --output-dir data/results

# Skip the download step (use cached data):
    python scripts/run_analysis.py --neighborhood "Lyon Park" --skip-download
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root setup
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("run_analysis")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_data_freshness(raw_dir: Path) -> None:
    """Print data freshness report from download_metadata.json."""
    metadata_path = raw_dir / "download_metadata.json"
    if not metadata_path.exists():
        logger.warning("No download metadata found; data may not have been downloaded yet.")
        return

    with open(metadata_path) as f:
        meta = json.load(f)

    print("\n=== Data Freshness ===")
    for key, info in meta.items():
        downloaded_at = info.get("downloaded_at", "unknown")
        feature_count = info.get("feature_count", "?")
        if downloaded_at != "unknown":
            try:
                dt = datetime.fromisoformat(downloaded_at)
                age_days = (datetime.now() - dt).days
                flag = " [STALE — consider --force-refresh]" if age_days > 90 else ""
                print(f"  {key:<25} {age_days:>4} days old   {feature_count:>8,} records{flag}")
            except Exception:
                print(f"  {key:<25} downloaded: {downloaded_at}  records: {feature_count}")
        else:
            print(f"  {key:<25} downloaded: unknown")
    print()


def _warn_if_stale(raw_dir: Path, threshold_days: int = 90) -> None:
    """Log a warning if any dataset is older than threshold_days."""
    metadata_path = raw_dir / "download_metadata.json"
    if not metadata_path.exists():
        return
    with open(metadata_path) as f:
        meta = json.load(f)
    for key, info in meta.items():
        downloaded_at = info.get("downloaded_at", "")
        if downloaded_at:
            try:
                dt = datetime.fromisoformat(downloaded_at)
                age_days = (datetime.now() - dt).days
                if age_days > threshold_days:
                    logger.warning(
                        f"Dataset '{key}' is {age_days} days old. "
                        "Use --force-refresh to re-download."
                    )
            except Exception:
                pass


def _download_data(raw_dir: Path, force: bool = False) -> None:
    """Download all required datasets."""
    from src.data import ArlingtonDataDownloader

    logger.info(f"Downloading data to {raw_dir} (force={force})...")
    downloader = ArlingtonDataDownloader(raw_dir)
    paths = downloader.download_all(force=force)

    success = [k for k, v in paths.items() if v is not None]
    failed = [k for k, v in paths.items() if v is None]

    logger.info(f"Downloaded: {', '.join(success)}")
    if failed:
        logger.warning(f"Failed to download: {', '.join(failed)}")


def _process_data(raw_dir: Path, processed_path: Path) -> "gpd.GeoDataFrame":
    """Load raw data and run the processing pipeline."""
    import geopandas as gpd
    import pandas as pd
    from src.data import DataProcessor
    import json as _json

    logger.info("Loading datasets...")
    parcels = gpd.read_file(raw_dir / "parcels.geojson")
    zoning = gpd.read_file(raw_dir / "zoning.geojson")

    glup = None
    glup_path = raw_dir / "glup.geojson"
    if glup_path.exists():
        glup = gpd.read_file(glup_path)

    civic_associations = None
    ca_path = raw_dir / "civic_associations.geojson"
    if ca_path.exists():
        civic_associations = gpd.read_file(ca_path)
        logger.info(f"Loaded {len(civic_associations)} civic association polygons")
    else:
        logger.warning(
            "civic_associations.geojson not found; neighborhood filtering unavailable. "
            "Re-run without --skip-download to fetch this dataset."
        )

    property_df = None
    property_path = raw_dir / "property.json"
    if property_path.exists():
        logger.info("Loading property data...")
        with open(property_path) as f:
            property_df = pd.DataFrame(_json.load(f))

    assessment_df = None
    assessment_path = raw_dir / "assessment.json"
    if assessment_path.exists():
        logger.info("Loading assessment data...")
        with open(assessment_path) as f:
            assessment_df = pd.DataFrame(_json.load(f))

    processor = DataProcessor(
        parcels_gdf=parcels,
        zoning_gdf=zoning,
        glup_gdf=glup,
        property_df=property_df,
        assessment_df=assessment_df,
        civic_associations_gdf=civic_associations,
    )

    logger.info("Processing data (spatial joins)...")
    enriched = processor.process_all(output_path=processed_path)
    logger.info(f"Processed {len(enriched):,} parcels → saved to {processed_path}")
    return enriched


def _load_processed(processed_path: Path) -> "gpd.GeoDataFrame":
    """Load previously processed enriched parcels."""
    import geopandas as gpd
    logger.info(f"Loading processed data from {processed_path}...")
    return gpd.read_file(processed_path)


def _list_neighborhoods(enriched: "gpd.GeoDataFrame") -> list[str]:
    """Return sorted list of civic association names present in the data."""
    if "civic_association" not in enriched.columns:
        return []
    names = (
        enriched["civic_association"]
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(names)


def _filter_to_neighborhood(
    enriched: "gpd.GeoDataFrame", neighborhood: str
) -> "gpd.GeoDataFrame":
    """Filter enriched GeoDataFrame to a single civic association name."""
    if "civic_association" not in enriched.columns:
        raise ValueError(
            "No 'civic_association' column found. "
            "Ensure civic_associations.geojson was downloaded and processed."
        )
    filtered = enriched[enriched["civic_association"] == neighborhood].copy()
    if len(filtered) == 0:
        raise ValueError(
            f"No parcels found for neighborhood '{neighborhood}'. "
            "Use --list-neighborhoods to see available names."
        )
    return filtered


def _run_analysis(
    parcels: "gpd.GeoDataFrame",
    config_dir: Path,
    label: str,
) -> "gpd.GeoDataFrame":
    """Run the full 4-stage analysis pipeline on a parcel GeoDataFrame."""
    from src.analysis import estimate_valuation_geodataframe

    # Property class codes to always exclude from residential analysis.
    # 201 = "GenCom VacLand-siteplan": commercial vacant land
    # 210 = "General Comm Parking": commercial parking lots
    # (510 = "Res - Vacant (SF & Twnhse)" is handled separately below
    #  because it includes both buildable lots AND alley/strip remnants.)
    ALWAYS_EXCLUDED_CLASSES = {"201", "210"}

    # Zoning districts in scope for the analysis.
    # Limited to pure one-family (and restricted two-family) districts where
    # by-right development standards are straightforward and unambiguous.
    # Excluded: R2-7 (two-family/townhouse with sub-minimum lots),
    #           R15-30T (townhouse district with small parcels along arterials),
    #           R-10T (townhouse overlay complicates by-right standards).
    INCLUDED_ZONES = {"R-5", "R-6", "R-8", "R-10", "R-20"}

    residential = parcels[parcels.get("is_residential_zoning", False) == True].copy()  # noqa: E712

    # Filter to in-scope zoning districts.
    n_excluded_zone = 0
    if "zoning_district" in residential.columns:
        before = len(residential)
        residential = residential[
            residential["zoning_district"].isin(INCLUDED_ZONES)
        ].copy()
        n_excluded_zone = before - len(residential)
        if n_excluded_zone:
            logger.info(
                f"[{label}] Excluded {n_excluded_zone:,} parcel(s) in out-of-scope "
                f"zoning districts (R2-7, R15-30T, R-10T); "
                f"analysis limited to {', '.join(sorted(INCLUDED_ZONES))}"
            )

    # Exclude commercial/parking classes unconditionally.
    n_excluded_class = 0
    if "propertyClassTypeCode" in residential.columns:
        before = len(residential)
        excluded = residential["propertyClassTypeCode"].astype(str).str[:3].isin(ALWAYS_EXCLUDED_CLASSES)
        residential = residential[~excluded].copy()
        n_excluded_class = before - len(residential)
        if n_excluded_class:
            logger.info(f"[{label}] Excluded {n_excluded_class:,} parcel(s) with non-residential property class (201/210)")

    # For class 510 ("Res - Vacant"), distinguish buildable lots from
    # alley remnants / strips by parcel size:
    #   GIS area < 80% of zoning min_lot_area_sf  →  remnant (exclude)
    #   GIS area >= 80% of zoning min_lot_area_sf →  potentially buildable (keep)
    n_excluded_510_remnant = 0
    if "propertyClassTypeCode" in residential.columns:
        from src.rules.engine import ZoningRulesEngine
        _rules = ZoningRulesEngine(config_dir)

        def _is_510_remnant(row) -> bool:
            if str(row.get("propertyClassTypeCode", ""))[:3] != "510":
                return False
            district = row.get("zoning_district")
            if not district:
                return True  # No zoning info; treat conservatively as remnant
            standards = _rules.get_standards(str(district))
            if standards is None or standards.min_lot_area_sf <= 0:
                return False  # Unknown district; keep it
            return (row.geometry.area if row.geometry else 0) < 0.80 * standards.min_lot_area_sf

        before = len(residential)
        is_remnant = residential.apply(_is_510_remnant, axis=1)
        n_excluded_510_remnant = int(is_remnant.sum())
        residential = residential[~is_remnant].copy()
        if n_excluded_510_remnant:
            logger.info(
                f"[{label}] Excluded {n_excluded_510_remnant:,} vacant-class (510) parcel(s) "
                f"below 80% of minimum lot size (likely alley/strip remnants)"
            )

    # Exclude parcels with no property API record at all.
    # These parcels have no property class, address, or building data from the
    # property API — they are likely alley remnants, strips, or administrative
    # parcels that were not registered in the county property database.
    # Limitation: a small number of legitimately-developable parcels with
    # incomplete property API coverage may also be excluded by this rule.
    n_excluded_no_join = 0
    property_join_col = "propertyStreetNbrNameText"
    property_class_col = "propertyClassTypeCode"
    if property_join_col in residential.columns and property_class_col in residential.columns:
        before = len(residential)
        no_join = (
            residential[property_join_col].isna()
            & residential[property_class_col].isna()
        )
        residential = residential[~no_join].copy()
        n_excluded_no_join = before - len(residential)
        if n_excluded_no_join:
            logger.info(
                f"[{label}] Excluded {n_excluded_no_join:,} parcel(s) with no property API record "
                f"(likely alley remnants or administrative parcels)"
            )

    # Exclude parcels where a building exists (year built recorded) but the
    # assessment API returned no improvement value — making GFA estimation
    # impossible.  These parcels produce "building_detected_no_gfa_data" in
    # the analysis, which means available-rights and valuation cannot be
    # computed.  Manual spot-checking across Alcova Heights confirmed that
    # all such parcels should be excluded.
    n_excluded_no_gfa = 0
    year_col = "propertyYearBuilt"
    imp_col = "improvementValueAmt"
    gfa_col = "grossFloorAreaSquareFeetQty"
    if year_col in residential.columns and imp_col in residential.columns:
        import pandas as _pd_filter
        year_vals = _pd_filter.to_numeric(residential[year_col], errors="coerce")
        imp_vals = _pd_filter.to_numeric(residential[imp_col], errors="coerce")
        gfa_vals = _pd_filter.to_numeric(
            residential[gfa_col], errors="coerce"
        ) if gfa_col in residential.columns else _pd_filter.Series(0, index=residential.index)

        has_building = year_vals.notna() & (year_vals > 0)
        no_improvement = imp_vals.isna() | (imp_vals <= 5_000)
        no_gfa_api = gfa_vals.isna() | (gfa_vals <= 0)
        no_gfa_data = has_building & no_improvement & no_gfa_api

        before = len(residential)
        residential = residential[~no_gfa_data].copy()
        n_excluded_no_gfa = before - len(residential)
        if n_excluded_no_gfa:
            logger.info(
                f"[{label}] Excluded {n_excluded_no_gfa:,} parcel(s) with building "
                f"but no improvement value (GFA cannot be estimated)"
            )

    # Exclude parcels explicitly marked "excluded" in the persistent spot-checks
    # file.  This allows analysts to record human review decisions (e.g. non-
    # residential use, missing data) and have them automatically applied on
    # every subsequent run without changing pipeline logic.
    import pandas as _pd
    _sc_path = (
        _PROJECT_ROOT / "data" / "results"
        / label.replace(" ", "_").lower()
        / "spot_checks.csv"
    )
    if _sc_path.exists():
        _sc = _pd.read_csv(_sc_path, dtype=str)
        _excluded_ids = set(
            _sc.loc[_sc["spot_check_result"].str.lower() == "excluded", "parcel_id"]
        )
        if _excluded_ids and "RPCMSTR" in residential.columns:
            before = len(residential)
            residential = residential[
                ~residential["RPCMSTR"].astype(str).isin(_excluded_ids)
            ].copy()
            n_excluded_spot_check = before - len(residential)
            if n_excluded_spot_check:
                logger.info(
                    f"[{label}] Excluded {n_excluded_spot_check:,} parcel(s) "
                    f"per spot-check exclusion records"
                )

    total = len(parcels)
    res_count = len(residential)

    logger.info(
        f"[{label}] Analyzing {res_count:,} residential parcels "
        f"(of {total:,} total)..."
    )

    if res_count == 0:
        logger.warning(f"[{label}] No residential parcels found; skipping analysis.")
        return parcels

    result_gdf = estimate_valuation_geodataframe(
        gdf=residential,
        config_dir=config_dir,
    )
    logger.info(f"[{label}] Analysis complete.")
    return result_gdf


# ---------------------------------------------------------------------------
# Output schema — ordered list of (raw_col, output_col) pairs
# ---------------------------------------------------------------------------

# Maps raw pipeline column names → clean output column names.
# Order determines column order in CSV / GeoJSON.
_OUTPUT_SCHEMA = [
    # Identity
    ("RPCMSTR",                       "parcel_id"),
    ("street_address",                "street_address"),
    ("civic_association",             "neighborhood"),
    # Zoning
    ("zoning_district",               "zoning_district"),
    ("is_split_zoned",                "is_split_zoned"),
    # Lot
    ("lot_area_sf",                   "lot_area_sf"),
    ("lot_width_ft",                  "lot_width_ft"),
    ("is_conforming",                 "is_conforming"),
    # Current building
    ("year_built",                    "year_built"),
    ("propertyClassTypeDsc",          "property_type"),
    ("current_gfa_sf",                "current_gfa_sf"),
    ("current_stories",               "current_stories"),
    ("landValueAmt",                  "land_value"),
    ("improvementValueAmt",           "improvement_value"),
    # Max allowed (by-right)
    ("max_footprint_sf",              "max_footprint_sf"),
    ("valuation_max_gfa_sf",          "max_gfa_sf"),
    ("max_height_ft",                 "max_height_ft"),
    ("max_dwelling_units",            "max_dwelling_units"),
    # Available rights
    ("valuation_available_gfa_sf",    "available_gfa_sf"),
    ("gfa_utilization_pct",           "gfa_utilization_pct"),
    ("development_status",            "development_status"),   # derived below
    ("gfa_source",                    "gfa_source"),
    # Valuation
    ("estimated_value_low",           "est_value_low"),
    ("estimated_value_high",          "est_value_high"),
    ("valuation_confidence",          "valuation_confidence"),
    # Neighborhood calibration
    ("neighborhood_imp_rate_median",  "neighborhood_imp_rate_median"),
    ("neighborhood_imp_rate_low",     "neighborhood_imp_rate_low"),
    ("neighborhood_imp_rate_high",    "neighborhood_imp_rate_high"),
    ("neighborhood_imp_rate_sample",  "neighborhood_imp_rate_sample"),
    # Spot checks (merged from persistent spot_checks.csv)
    ("spot_check_result",             "spot_check_result"),
    ("spot_check_notes",              "spot_check_notes"),
    ("spot_check_date",               "spot_check_date"),
]


def _add_development_status(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """
    Derive a plain-language development_status column.

    Categories:
      vacant           — no building on parcel
      underdeveloped   — built to < 80 % of zoning limit
      near-capacity    — built to 80–100 % of zoning limit
      overdeveloped    — existing building exceeds current zoning limit
      unknown          — insufficient data to determine
    """
    def _classify(row) -> str:
        if row.get("gfa_source") == "building_detected_no_gfa_data":
            return "built-no-data"
        if row.get("is_vacant") is True:
            return "vacant"
        if row.get("is_overdeveloped") is True:
            return "overdeveloped"
        util = row.get("gfa_utilization_pct")
        if util is None:
            return "unknown"
        if util < 80:
            return "underdeveloped"
        return "near-capacity"

    gdf = gdf.copy()
    gdf["development_status"] = gdf.apply(_classify, axis=1)
    return gdf


def _curate_output(result_gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """
    Apply the target output schema: select, rename, and order columns.

    Only columns defined in _OUTPUT_SCHEMA are kept. Geometry is preserved.
    Columns missing from the raw pipeline are silently skipped.
    """
    renames = {}
    ordered = []
    for raw_col, out_col in _OUTPUT_SCHEMA:
        if raw_col in result_gdf.columns:
            renames[raw_col] = out_col
            ordered.append(out_col)

    curated = result_gdf.rename(columns=renames)
    keep = [c for c in ordered if c in curated.columns] + ["geometry"]
    return curated[[c for c in keep if c in curated.columns]]


def _save_data_dictionary(output_dir: Path, config_dir: Path, label: str) -> None:
    """Write a data_dictionary.csv alongside the analysis results."""
    import csv as _csv

    dict_path = config_dir / "data_dictionary.json"
    if not dict_path.exists():
        logger.warning(f"data_dictionary.json not found at {dict_path}; skipping.")
        return

    with open(dict_path, encoding="utf-8") as f:
        dd = json.load(f)

    # Build a lookup of field → entry
    entries = {e["field"]: e for e in dd.get("columns", [])}

    # Write only the fields present in the output schema
    out_path = output_dir / "data_dictionary.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = _csv.writer(f)
        writer.writerow(["field", "label", "description", "source", "example"])
        for _raw, out_col in _OUTPUT_SCHEMA:
            entry = entries.get(out_col, {})
            writer.writerow([
                out_col,
                entry.get("label", out_col),
                entry.get("description", ""),
                entry.get("source", ""),
                entry.get("example", ""),
            ])

    logger.info(f"  Saved data dict:  {out_path}")


def _load_spot_checks(output_dir: Path) -> "pd.DataFrame":
    """
    Load the persistent spot-checks file for a neighborhood.

    The file (spot_checks.csv) lives alongside the analysis output and is
    NEVER overwritten by the analysis pipeline — only read.  Analysts add
    rows manually or via tooling to record parcel-level verifications.

    Expected columns: parcel_id, spot_check_result, spot_check_notes, spot_check_date

    Returns an empty DataFrame (with those columns) if the file does not exist.
    """
    import pandas as pd

    sc_cols = ["parcel_id", "spot_check_result", "spot_check_notes", "spot_check_date"]
    path = output_dir / "spot_checks.csv"
    if not path.exists():
        return pd.DataFrame(columns=sc_cols)

    df = pd.read_csv(path, dtype=str)
    # Ensure all expected columns are present
    for col in sc_cols:
        if col not in df.columns:
            df[col] = None
    return df[sc_cols]


def _save_results(
    result_gdf: "gpd.GeoDataFrame",
    output_dir: Path,
    label: str,
    config_dir: Path,
) -> None:
    """Save curated analysis results to GeoPackage, GeoJSON, CSV, and summary."""
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)

    safe_label = label.replace(" ", "_").replace("/", "-").lower()

    # --- Derive development_status before curation ---
    result_gdf = _add_development_status(result_gdf)

    # --- Merge persistent spot-check records ---
    spot_checks = _load_spot_checks(output_dir)
    if not spot_checks.empty:
        spot_checks["parcel_id"] = spot_checks["parcel_id"].astype(str)
        # Identify the raw parcel-ID column before renaming
        raw_id_col = next(
            (raw for raw, out in _OUTPUT_SCHEMA if out == "parcel_id"),
            "RPCMSTR",
        )
        if raw_id_col in result_gdf.columns:
            result_gdf = result_gdf.copy()
            result_gdf[raw_id_col] = result_gdf[raw_id_col].astype(str)
            result_gdf = result_gdf.merge(
                spot_checks.rename(columns={"parcel_id": raw_id_col}),
                on=raw_id_col,
                how="left",
            )
            n_matched = result_gdf["spot_check_result"].notna().sum()
            logger.info(f"  Merged {n_matched} spot-check record(s) into output")

    # --- Apply output schema ---
    curated = _curate_output(result_gdf)

    gpkg_path    = output_dir / f"{safe_label}_analysis.gpkg"
    geojson_path = output_dir / f"{safe_label}_analysis.geojson"
    csv_path     = output_dir / f"{safe_label}_analysis.csv"
    summary_path = output_dir / f"{safe_label}_summary.txt"

    # GeoPackage (keeps original CRS)
    curated.to_file(gpkg_path, driver="GPKG")
    logger.info(f"  Saved GeoPackage: {gpkg_path}")

    # GeoJSON (WGS84 — required for web maps)
    curated_wgs84 = curated.to_crs("EPSG:4326")
    curated_wgs84.to_file(geojson_path, driver="GeoJSON")
    logger.info(f"  Saved GeoJSON:    {geojson_path}")

    # CSV (no geometry)
    csv_df = curated.drop(columns=["geometry"], errors="ignore")
    csv_df.to_csv(csv_path, index=False)
    logger.info(f"  Saved CSV:        {csv_path}")

    # Data dictionary
    _save_data_dictionary(output_dir, config_dir, label)

    # Summary
    summary = _build_summary(curated, label)
    summary_path.write_text(summary, encoding="utf-8")
    logger.info(f"  Saved summary:    {summary_path}")

    print(f"\n{'='*60}")
    print(f"  Results for: {label}")
    print(f"{'='*60}")
    print(summary)


def _build_summary(result_gdf: "gpd.GeoDataFrame", label: str) -> str:
    """Build a human-readable summary of analysis results."""
    lines = [
        f"Analysis Summary: {label}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
    ]

    total = len(result_gdf)
    lines.append(f"\nTotal residential parcels analyzed: {total:,}")

    # Conformance
    if "is_conforming" in result_gdf.columns:
        conforming = result_gdf["is_conforming"].sum()
        lines.append(f"Conforming parcels: {conforming:,} ({conforming/total*100:.1f}%)")

    # Zoning breakdown
    if "zoning_district" in result_gdf.columns:
        zones = result_gdf["zoning_district"].value_counts()
        lines.append("\nZoning district breakdown:")
        for zone, count in zones.head(10).items():
            lines.append(f"  {zone:<12} {count:>6,} parcels")

    # Development status
    if "development_status" in result_gdf.columns:
        statuses = result_gdf["development_status"].value_counts()
        lines.append("\nDevelopment status:")
        for status, count in statuses.items():
            lines.append(f"  {status:<16} {count:>6,} parcels")

    # Available rights
    if "available_gfa_sf" in result_gdf.columns:
        avail = result_gdf["available_gfa_sf"].dropna()
        positive = avail[avail > 0]
        if len(positive) > 0:
            lines.extend([
                "\nUnused GFA Capacity (parcels with positive available rights):",
                f"  Parcels with capacity: {len(positive):,}",
                f"  Total available SF:    {positive.sum():>12,.0f} sf",
                f"  Median per parcel:     {positive.median():>12,.0f} sf",
            ])

    # Neighborhood improvement rate calibration
    if "neighborhood_imp_rate_median" in result_gdf.columns:
        import pandas as _pd_summary
        rate_median = result_gdf["neighborhood_imp_rate_median"].iloc[0]
        rate_low = result_gdf["neighborhood_imp_rate_low"].iloc[0]
        rate_high = result_gdf["neighborhood_imp_rate_high"].iloc[0]
        rate_sample = result_gdf["neighborhood_imp_rate_sample"].iloc[0]
        if rate_median is not None and not _pd_summary.isna(rate_median):
            lines.extend([
                "\nNeighborhood Improvement Rate Calibration:",
                f"  Median $/SF:     ${rate_median:>10,.0f}",
                f"  Range:           ${rate_low:>10,.0f} – ${rate_high:,.0f}",
                f"  Sample size:     {int(rate_sample):>10,} recent builds",
            ])

    # Valuation
    if "est_value_low" in result_gdf.columns:
        valued = result_gdf[result_gdf["est_value_low"].notna()]
        if len(valued) > 0:
            total_low = valued["est_value_low"].sum()
            total_high = valued["est_value_high"].sum()
            lines.extend([
                "\nValuation (parcels with positive available rights):",
                f"  Parcels valued:     {len(valued):>10,}",
                f"  Aggregate low:      ${total_low:>14,.0f}",
                f"  Aggregate high:     ${total_high:>14,.0f}",
            ])

            if "valuation_confidence" in result_gdf.columns:
                conf_counts = result_gdf["valuation_confidence"].value_counts()
                lines.append("  Confidence levels:")
                for level, count in conf_counts.items():
                    lines.append(f"    {level:<16} {count:>6,}")

    lines.append("\n" + "=" * 60)
    lines.append(
        "DISCLAIMER: Valuation estimates are for policy analysis only,\n"
        "not property appraisals. Calibrate market parameters before use."
    )
    lines.append(
        "\nLIMITATION: Parcels with no record in the Arlington property API\n"
        "(typically alley remnants, strips, or administrative parcels) are\n"
        "excluded from this analysis. A small number of legitimately\n"
        "developable parcels with incomplete API coverage may also be excluded."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Arlington Zoning Analyzer — Analysis Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/run_analysis.py --list-neighborhoods
              python scripts/run_analysis.py --neighborhood "Lyon Park"
              python scripts/run_analysis.py --all-neighborhoods
              python scripts/run_analysis.py --check-data
              python scripts/run_analysis.py --neighborhood "Lyon Park" --force-refresh
        """),
    )

    # Mode flags (mutually exclusive)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--neighborhood", metavar="NAME",
        help="Run analysis for a single civic association neighborhood (MVP mode)"
    )
    mode.add_argument(
        "--all-neighborhoods", action="store_true",
        help="Run analysis for every civic association neighborhood (batch mode)"
    )
    mode.add_argument(
        "--list-neighborhoods", action="store_true",
        help="List available neighborhood names and exit (requires processed data)"
    )
    mode.add_argument(
        "--check-data", action="store_true",
        help="Report data freshness and exit"
    )

    # Paths
    parser.add_argument(
        "--data-dir", default="data/raw",
        help="Directory for raw downloaded data (default: data/raw)"
    )
    parser.add_argument(
        "--processed-path", default="data/processed/parcels_enriched.gpkg",
        help="Path for the processed GeoPackage (default: data/processed/parcels_enriched.gpkg)"
    )
    parser.add_argument(
        "--output-dir", default="data/results",
        help="Output directory for analysis results (default: data/results)"
    )
    parser.add_argument(
        "--config-dir", default="config",
        help="Config directory containing zoning rules (default: config)"
    )

    # Download control
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Skip the download step and use cached data"
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Force re-download of all source datasets"
    )
    parser.add_argument(
        "--skip-process", action="store_true",
        help="Skip processing step and load from --processed-path directly"
    )

    # Logging
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Resolve paths relative to project root
    raw_dir = (_PROJECT_ROOT / args.data_dir).resolve()
    processed_path = (_PROJECT_ROOT / args.processed_path).resolve()
    output_dir = (_PROJECT_ROOT / args.output_dir).resolve()
    config_dir = (_PROJECT_ROOT / args.config_dir).resolve()

    # --check-data mode
    if args.check_data:
        _check_data_freshness(raw_dir)
        return

    # Ensure we have a mode selected
    if not args.neighborhood and not args.all_neighborhoods and not args.list_neighborhoods:
        parser.print_help()
        print(
            "\nError: Specify --neighborhood NAME, --all-neighborhoods, "
            "--list-neighborhoods, or --check-data"
        )
        sys.exit(1)

    # --- Step 1: Download ---
    if args.force_refresh:
        _download_data(raw_dir, force=True)
    elif not args.skip_download:
        # Check if any required data is missing; download if so
        required = [
            raw_dir / "parcels.geojson",
            raw_dir / "zoning.geojson",
            raw_dir / "civic_associations.geojson",
            raw_dir / "property.json",
            raw_dir / "assessment.json",
        ]
        missing = [p for p in required if not p.exists()]
        if missing:
            logger.info(
                f"Missing data files ({[p.name for p in missing]}); downloading..."
            )
            _download_data(raw_dir, force=False)
        else:
            logger.info("Data files present; skipping download (use --force-refresh to re-download)")
            _warn_if_stale(raw_dir)

    # --- Step 2: Process ---
    if args.skip_process and processed_path.exists():
        enriched = _load_processed(processed_path)
    else:
        if not (raw_dir / "parcels.geojson").exists():
            logger.error(
                f"parcels.geojson not found in {raw_dir}. "
                "Run without --skip-download to download data first."
            )
            sys.exit(1)
        enriched = _process_data(raw_dir, processed_path)

    # --list-neighborhoods mode
    if args.list_neighborhoods:
        neighborhoods = _list_neighborhoods(enriched)
        if not neighborhoods:
            print(
                "No civic_association column found in processed data.\n"
                "Ensure civic_associations.geojson was downloaded and re-run processing."
            )
            sys.exit(1)
        print(f"\nAvailable neighborhoods ({len(neighborhoods)}):")
        for name in neighborhoods:
            count = (enriched["civic_association"] == name).sum()
            print(f"  {name:<40} ({count:,} parcels)")
        return

    # --- Step 3+: Analysis ---
    if args.neighborhood:
        # MVP: single neighborhood
        neighborhood = args.neighborhood
        logger.info(f"Filtering to neighborhood: '{neighborhood}'")
        try:
            subset = _filter_to_neighborhood(enriched, neighborhood)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

        logger.info(f"Found {len(subset):,} parcels in '{neighborhood}'")
        result = _run_analysis(subset, config_dir, label=neighborhood)
        _save_results(result, output_dir / neighborhood.replace(" ", "_").lower(), neighborhood, config_dir)

    elif args.all_neighborhoods:
        # Batch: all neighborhoods
        neighborhoods = _list_neighborhoods(enriched)
        if not neighborhoods:
            logger.error(
                "No civic_association column found. "
                "Cannot run batch mode without neighborhood data."
            )
            sys.exit(1)

        logger.info(f"Batch mode: processing {len(neighborhoods)} neighborhoods...")
        import pandas as pd

        all_results = []
        failed = []

        for i, neighborhood in enumerate(neighborhoods, 1):
            logger.info(f"[{i}/{len(neighborhoods)}] {neighborhood}")
            try:
                subset = _filter_to_neighborhood(enriched, neighborhood)
                result = _run_analysis(subset, config_dir, label=neighborhood)
                _save_results(
                    result,
                    output_dir / neighborhood.replace(" ", "_").lower(),
                    neighborhood,
                    config_dir,
                )
                all_results.append(result)
            except Exception as e:
                logger.error(f"Failed to process '{neighborhood}': {e}")
                failed.append(neighborhood)

        # Aggregate summary CSV
        if all_results:
            agg_df = pd.concat(
                [r.drop(columns=["geometry"], errors="ignore") for r in all_results],
                ignore_index=True,
            )
            agg_path = output_dir / "all_neighborhoods_combined.csv"
            output_dir.mkdir(parents=True, exist_ok=True)
            agg_df.to_csv(agg_path, index=False)
            logger.info(f"Saved combined results: {agg_path}")

        if failed:
            logger.warning(f"Failed neighborhoods ({len(failed)}): {', '.join(failed)}")

        print(f"\nBatch complete: {len(all_results)} succeeded, {len(failed)} failed.")


if __name__ == "__main__":
    main()
