"""
Parcel Inspection / Pipeline Validation
========================================

Single-parcel inspector that re-runs the full analysis pipeline and
surfaces every intermediate value, making it trivial to spot where an
error or incorrect assumption enters the analysis.

Usage (programmatic)::

    from src.analysis.inspector import inspect_parcel
    result = inspect_parcel("06017024", enriched_gdf, config_dir="config")
    print(result.report())

Usage (CLI)::

    python scripts/inspect_parcel.py --parcel-id "06017024"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from .development_potential import (
    DevelopmentPotentialAnalyzer,
    DevelopmentPotentialResult,
)
from .current_built import (
    CurrentBuiltResult,
    NeighborhoodRate,
    analyze_current_built,
    estimate_neighborhood_improvement_rate,
)
from .available_rights import (
    AvailableRightsResult,
    calculate_available_rights,
    DEFAULT_ASSUMED_STORIES,
)
from .valuation import (
    ValuationResult,
    ValuationParams,
    ValuationMethodResult,
    ConfidenceLevel,
    calculate_valuation,
    load_valuation_params,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrored from run_analysis.py to avoid importing the script)
# ---------------------------------------------------------------------------

_INCLUDED_ZONES = {"R-5", "R-6", "R-8", "R-10", "R-20"}
_ALWAYS_EXCLUDED_CLASSES = {"201", "210"}
_PROPERTY_CODE_PREFIX_LEN = 3
_IMPROVEMENT_VALUE_THRESHOLD = 5_000.0


# ---------------------------------------------------------------------------
# Exclusion filter diagnosis
# ---------------------------------------------------------------------------

@dataclass
class ExclusionCheckResult:
    """Result of a single exclusion filter check against a parcel."""
    filter_name: str
    passed: bool
    reason: str


def check_exclusion_filters(
    parcel_row: pd.Series,
    config_dir: str | Path = "config",
    output_dir: Path | None = None,
) -> list[ExclusionCheckResult]:
    """
    Run each exclusion filter against a single parcel.

    Returns a list of ExclusionCheckResult, one per filter, indicating
    whether the parcel passes (is kept) or fails (would be excluded).
    """
    from ..rules.engine import ZoningRulesEngine

    results: list[ExclusionCheckResult] = []
    config_dir = Path(config_dir)

    # 1. Residential zoning check
    is_res = parcel_row.get("is_residential_zoning")
    zoning = parcel_row.get("zoning_district")
    is_res_truthy = bool(is_res) if is_res is not None and not (isinstance(is_res, float) and pd.isna(is_res)) else False
    if not is_res_truthy:
        results.append(ExclusionCheckResult(
            "Residential zoning",
            passed=False,
            reason=f"Not flagged as residential zoning (is_residential_zoning={is_res})",
        ))
    elif zoning and str(zoning) not in _INCLUDED_ZONES:
        results.append(ExclusionCheckResult(
            "Residential zoning",
            passed=False,
            reason=f"{zoning} is not in scope ({', '.join(sorted(_INCLUDED_ZONES))})",
        ))
    else:
        results.append(ExclusionCheckResult(
            "Residential zoning",
            passed=True,
            reason=f"{zoning} is in scope",
        ))

    # 2. Property class check
    class_code = str(parcel_row.get("propertyClassTypeCode", "") or "")
    prefix = class_code[:_PROPERTY_CODE_PREFIX_LEN]
    if prefix in _ALWAYS_EXCLUDED_CLASSES:
        results.append(ExclusionCheckResult(
            "Property class",
            passed=False,
            reason=f"Class prefix {prefix} is excluded (201=commercial vacant, 210=commercial parking)",
        ))
    else:
        results.append(ExclusionCheckResult(
            "Property class",
            passed=True,
            reason=f"{class_code or 'N/A'} is not excluded (201/210)",
        ))

    # 3. Class 510 remnant check
    if prefix == "510":
        rules = ZoningRulesEngine(config_dir)
        standards = rules.get_standards(str(zoning)) if zoning and not pd.isna(zoning) else None
        geom = parcel_row.get("geometry")
        area = geom.area if geom is not None else 0
        if standards and standards.min_lot_area_sf > 0:
            threshold = 0.80 * standards.min_lot_area_sf
            if area < threshold:
                results.append(ExclusionCheckResult(
                    "Class 510 remnant",
                    passed=False,
                    reason=(
                        f"Vacant (510), area {area:,.0f} sf < 80% of min lot "
                        f"({standards.min_lot_area_sf:,} sf) = {threshold:,.0f} sf"
                    ),
                ))
            else:
                results.append(ExclusionCheckResult(
                    "Class 510 remnant",
                    passed=True,
                    reason=(
                        f"Vacant (510) but area {area:,.0f} sf >= 80% of min lot "
                        f"({threshold:,.0f} sf) — potentially buildable"
                    ),
                ))
        else:
            results.append(ExclusionCheckResult(
                "Class 510 remnant",
                passed=True,
                reason="Class 510 but no zoning standards to compare against",
            ))
    else:
        results.append(ExclusionCheckResult(
            "Class 510 remnant",
            passed=True,
            reason=f"Not class 510 (class={class_code or 'N/A'})",
        ))

    # 4. No property record check
    address = parcel_row.get("propertyStreetNbrNameText")
    prop_class = parcel_row.get("propertyClassTypeCode")
    addr_missing = address is None or (isinstance(address, float) and pd.isna(address))
    class_missing = prop_class is None or (isinstance(prop_class, float) and pd.isna(prop_class))
    if addr_missing and class_missing:
        results.append(ExclusionCheckResult(
            "Property record",
            passed=False,
            reason="No address and no class code — likely no property API record",
        ))
    else:
        parts = []
        if not addr_missing:
            parts.append(f"address='{address}'")
        if not class_missing:
            parts.append(f"class={prop_class}")
        results.append(ExclusionCheckResult(
            "Property record",
            passed=True,
            reason=f"Has property data ({', '.join(parts)})",
        ))

    # 5. No GFA data check
    year_val = pd.to_numeric(parcel_row.get("propertyYearBuilt"), errors="coerce")
    imp_val = pd.to_numeric(parcel_row.get("improvementValueAmt"), errors="coerce")
    gfa_val = pd.to_numeric(parcel_row.get("grossFloorAreaSquareFeetQty"), errors="coerce")

    has_building = pd.notna(year_val) and year_val > 0
    no_improvement = pd.isna(imp_val) or imp_val <= _IMPROVEMENT_VALUE_THRESHOLD
    no_gfa_api = pd.isna(gfa_val) or gfa_val <= 0

    if has_building and no_improvement and no_gfa_api:
        results.append(ExclusionCheckResult(
            "GFA data",
            passed=False,
            reason=(
                f"Building detected (year built {int(year_val)}) but no improvement "
                f"value and no API GFA — cannot estimate floor area"
            ),
        ))
    else:
        parts = []
        if not pd.isna(gfa_val) and gfa_val > 0:
            parts.append(f"API GFA={gfa_val:,.0f} sf")
        if not pd.isna(imp_val) and imp_val > _IMPROVEMENT_VALUE_THRESHOLD:
            parts.append(f"improvement=${imp_val:,.0f}")
        if not has_building:
            parts.append("no building detected")
        results.append(ExclusionCheckResult(
            "GFA data",
            passed=True,
            reason=f"GFA estimable ({'; '.join(parts)})" if parts else "No building; vacant lot",
        ))

    # 6. Spot check exclusion
    if output_dir is not None:
        sc_path = output_dir / "spot_checks.csv"
        parcel_id = str(parcel_row.get("RPCMSTR", ""))
        if sc_path.exists():
            sc = pd.read_csv(sc_path, dtype=str)
            excluded_ids = set(
                sc.loc[sc["spot_check_result"].str.lower() == "excluded", "parcel_id"]
            )
            if parcel_id in excluded_ids:
                notes = ""
                if "spot_check_notes" in sc.columns:
                    notes_series = sc.loc[
                        (sc["parcel_id"] == parcel_id)
                        & (sc["spot_check_result"].str.lower() == "excluded"),
                        "spot_check_notes",
                    ]
                    notes = notes_series.iloc[0] if len(notes_series) > 0 else ""
                results.append(ExclusionCheckResult(
                    "Spot check",
                    passed=False,
                    reason=f"Excluded in spot_checks.csv" + (f": {notes}" if notes else ""),
                ))
            else:
                results.append(ExclusionCheckResult(
                    "Spot check",
                    passed=True,
                    reason="Not in spot_checks.csv as excluded",
                ))
        else:
            results.append(ExclusionCheckResult(
                "Spot check",
                passed=True,
                reason="No spot_checks.csv found",
            ))
    else:
        results.append(ExclusionCheckResult(
            "Spot check",
            passed=True,
            reason="No output_dir provided; spot check not evaluated",
        ))

    return results


# ---------------------------------------------------------------------------
# Inspection result
# ---------------------------------------------------------------------------

@dataclass
class ParcelInspectionResult:
    """Complete inspection trace of a single parcel through the full pipeline."""

    parcel_id: str
    raw_input_data: dict = field(default_factory=dict)
    exclusion_checks: list[ExclusionCheckResult] = field(default_factory=list)

    # Stage 1
    stage1_potential: Optional[DevelopmentPotentialResult] = None
    stage1_config_used: dict = field(default_factory=dict)

    # Stage 2
    stage2_current: Optional[CurrentBuiltResult] = None
    stage2_neighborhood_rate: Optional[NeighborhoodRate] = None

    # Stage 3
    stage3_rights: Optional[AvailableRightsResult] = None

    # Stage 4
    stage4_valuation: Optional[ValuationResult] = None
    stage4_params_used: Optional[ValuationParams] = None

    # Metadata
    parcel_found: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        d: dict = {
            "parcel_id": self.parcel_id,
            "parcel_found": self.parcel_found,
            "error": self.error,
            "raw_input_data": self.raw_input_data,
            "exclusion_checks": [
                {"filter_name": c.filter_name, "passed": c.passed, "reason": c.reason}
                for c in self.exclusion_checks
            ],
        }

        if self.stage1_potential:
            d["stage1_potential"] = self.stage1_potential.to_dict()
        d["stage1_config_used"] = self.stage1_config_used

        if self.stage2_current:
            d["stage2_current"] = self.stage2_current.to_dict()
        if self.stage2_neighborhood_rate:
            d["stage2_neighborhood_rate"] = {
                "median": self.stage2_neighborhood_rate.median,
                "low": self.stage2_neighborhood_rate.low,
                "high": self.stage2_neighborhood_rate.high,
                "sample_size": self.stage2_neighborhood_rate.sample_size,
                "fallback_used": self.stage2_neighborhood_rate.fallback_used,
            }

        if self.stage3_rights:
            d["stage3_rights"] = self.stage3_rights.to_dict()

        if self.stage4_valuation:
            d["stage4_valuation"] = self.stage4_valuation.to_dict()

        if self.stage4_params_used:
            d["stage4_params_used"] = {
                "market_to_assessment_ratio_low": self.stage4_params_used.market_to_assessment_ratio_low,
                "market_to_assessment_ratio_high": self.stage4_params_used.market_to_assessment_ratio_high,
                "price_per_gfa_sf_low": self.stage4_params_used.price_per_gfa_sf_low,
                "price_per_gfa_sf_high": self.stage4_params_used.price_per_gfa_sf_high,
                "price_per_unit_low": self.stage4_params_used.price_per_unit_low,
                "price_per_unit_high": self.stage4_params_used.price_per_unit_high,
                "land_residual_discount_low": self.stage4_params_used.land_residual_discount_low,
                "land_residual_discount_high": self.stage4_params_used.land_residual_discount_high,
                "residential_improvement_value_per_sf": self.stage4_params_used.residential_improvement_value_per_sf,
                "params_last_updated": self.stage4_params_used.params_last_updated,
            }

        return d

    def report(self) -> str:
        """Generate a full formatted text report."""
        return _format_report(self)


# ---------------------------------------------------------------------------
# Main inspection function
# ---------------------------------------------------------------------------

def inspect_parcel(
    parcel_id: str,
    enriched_gdf: gpd.GeoDataFrame,
    config_dir: str | Path = "config",
    output_dir: Path | None = None,
    neighborhood_gdf: gpd.GeoDataFrame | None = None,
    parcel_id_column: str = "RPCMSTR",
    zoning_column: str = "zoning_district",
) -> ParcelInspectionResult:
    """
    Run the full analysis pipeline on a single parcel and capture every
    intermediate value for inspection.

    Args:
        parcel_id: Parcel identifier (RPCMSTR) to inspect.
        enriched_gdf: Enriched GeoDataFrame from the processing pipeline.
        config_dir: Directory containing zoning rules and valuation config.
        output_dir: Neighborhood output directory (for spot_checks.csv lookup).
        neighborhood_gdf: GeoDataFrame filtered to the parcel's neighborhood,
            used for neighborhood rate calibration. If None, the full
            enriched_gdf is used (which may produce less accurate rates).
        parcel_id_column: Column containing parcel IDs.
        zoning_column: Column containing zoning district codes.

    Returns:
        ParcelInspectionResult with the full pipeline trace.
    """
    config_dir = Path(config_dir)
    result = ParcelInspectionResult(parcel_id=parcel_id)

    # Find the parcel
    mask = enriched_gdf[parcel_id_column].astype(str) == str(parcel_id)
    if not mask.any():
        result.error = f"Parcel '{parcel_id}' not found in dataset (column: {parcel_id_column})"
        return result

    result.parcel_found = True
    row = enriched_gdf.loc[mask].iloc[0]

    # Capture raw input data
    raw = {}
    for col in row.index:
        if col == "geometry":
            continue
        val = row[col]
        try:
            is_na = pd.isna(val)
            if isinstance(is_na, bool) and is_na:
                raw[col] = None
                continue
        except (TypeError, ValueError):
            pass
        raw[col] = val if isinstance(val, (int, float, str, bool)) else str(val)
    result.raw_input_data = raw

    # --- Exclusion filter checks ---
    result.exclusion_checks = check_exclusion_filters(row, config_dir, output_dir)

    # --- Stage 1: Development Potential ---
    zoning = row.get(zoning_column)
    is_split = row.get("is_split_zoned", False)

    # Use assessor's lot size when available
    lot_size_qty = pd.to_numeric(row.get("lotSizeQty"), errors="coerce")
    lot_size_override = lot_size_qty if pd.notna(lot_size_qty) and lot_size_qty > 0 else None

    if zoning is not None and not pd.isna(zoning):
        analyzer = DevelopmentPotentialAnalyzer(config_dir=config_dir)
        try:
            potential = analyzer.analyze(
                geometry=row.geometry,
                zoning_district=str(zoning),
                parcel_id=parcel_id,
                is_split_zoned=bool(is_split),
                lot_size_override=lot_size_override,
            )
            result.stage1_potential = potential

            # Capture the zoning config that was looked up (only on success)
            standards = analyzer.rules_engine.get_standards(str(zoning))
            if standards:
                result.stage1_config_used = {
                    "district_code": standards.district_code,
                    "district_name": standards.district_name,
                    "min_lot_area_sf": standards.min_lot_area_sf,
                    "min_lot_width_ft": standards.min_lot_width_ft,
                    "max_height_ft": standards.max_height_ft,
                    "max_lot_coverage_pct": standards.max_lot_coverage_pct,
                    "max_building_footprint_pct": standards.max_building_footprint_pct,
                    "max_building_footprint_sf": standards.max_building_footprint_sf,
                    "parking_spaces_per_unit": standards.parking_spaces_per_unit,
                }
        except Exception as e:
            result.stage1_potential = DevelopmentPotentialResult(
                parcel_id=parcel_id,
                zoning_district=str(zoning),
                analysis_errors=[f"Analysis error: {e}"],
            )
    else:
        result.stage1_potential = DevelopmentPotentialResult(
            parcel_id=parcel_id,
            analysis_errors=["No zoning district found for parcel"],
        )

    # --- Stage 2: Current Built ---
    # Compute neighborhood improvement rate
    rate_gdf = neighborhood_gdf if neighborhood_gdf is not None else enriched_gdf
    params = load_valuation_params(config_dir)

    neighborhood_rate = estimate_neighborhood_improvement_rate(
        rate_gdf,
        config_dir=config_dir,
        fallback_rate=params.residential_improvement_value_per_sf,
    )
    result.stage2_neighborhood_rate = neighborhood_rate

    current = analyze_current_built(
        row,
        parcel_id_column=parcel_id_column,
        improvement_value_per_sf=neighborhood_rate.median,
    )
    result.stage2_current = current

    # --- Stage 3: Available Rights ---
    if result.stage1_potential is not None:
        rights = calculate_available_rights(
            result.stage1_potential,
            current,
            DEFAULT_ASSUMED_STORIES,
        )
        result.stage3_rights = rights
    else:
        rights = None

    # --- Stage 4: Valuation ---
    result.stage4_params_used = params
    if rights is not None:
        valuation = calculate_valuation(rights, params)
        result.stage4_valuation = valuation

    return result


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _fmt(val, fmt_str: str = "", prefix: str = "", suffix: str = "", na: str = "N/A") -> str:
    """Format a value, returning na string if None."""
    if val is None:
        return na
    if isinstance(val, float) and pd.isna(val):
        return na
    if fmt_str:
        return f"{prefix}{val:{fmt_str}}{suffix}"
    return f"{prefix}{val}{suffix}"


def _format_report(r: ParcelInspectionResult) -> str:
    """Format a ParcelInspectionResult into a human-readable text report."""
    lines: list[str] = []
    sep = "=" * 80

    lines.append(sep)
    lines.append(f"PARCEL INSPECTION REPORT: {r.parcel_id}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(sep)

    if not r.parcel_found:
        lines.append(f"\nERROR: {r.error}")
        return "\n".join(lines)

    raw = r.raw_input_data

    # -- IDENTITY --
    lines.append("")
    lines.append("IDENTITY")
    lines.append(f"  Parcel ID:      {r.parcel_id}")
    lines.append(f"  Address:        {raw.get('street_address') or raw.get('propertyStreetNbrNameText') or 'N/A'}")
    lines.append(f"  Neighborhood:   {raw.get('civic_association', 'N/A')}")
    lines.append(f"  Zoning:         {raw.get('zoning_district', 'N/A')}")
    lines.append(f"  Split Zoned:    {'Yes' if raw.get('is_split_zoned') else 'No'}")

    # -- RAW INPUT DATA --
    lines.append("")
    lines.append("RAW INPUT DATA")
    key_fields = [
        "grossFloorAreaSquareFeetQty",
        "storyHeightCnt",
        "propertyYearBuilt",
        "numberOfUnitsCnt",
        "lotSizeQty",
        "improvementValueAmt",
        "landValueAmt",
        "totalValueAmt",
        "propertyClassTypeCode",
        "propertyClassTypeDsc",
    ]
    for k in key_fields:
        val = raw.get(k)
        if val is not None and isinstance(val, float):
            lines.append(f"  {k + ':':<36} {val:,.1f}")
        elif val is not None:
            lines.append(f"  {k + ':':<36} {val}")
        else:
            lines.append(f"  {k + ':':<36} None")

    # -- EXCLUSION FILTER CHECKS --
    lines.append("")
    lines.append("EXCLUSION FILTER CHECKS")
    for check in r.exclusion_checks:
        tag = "PASS" if check.passed else "FAIL"
        lines.append(f"  [{tag}] {check.filter_name}: {check.reason}")

    would_be_excluded = any(not c.passed for c in r.exclusion_checks)
    if would_be_excluded:
        lines.append("")
        lines.append("  >>> This parcel WOULD BE EXCLUDED from the analysis pipeline <<<")

    # -- STAGE 1 --
    lines.append("")
    lines.append("STAGE 1: DEVELOPMENT POTENTIAL")
    pot = r.stage1_potential
    if pot and pot.analysis_errors:
        for err in pot.analysis_errors:
            lines.append(f"  ERROR: {err}")
    elif pot:
        lines.append("  Lot Metrics:")
        area_src = pot.lot_area_source
        width_src = pot.lot_width_source
        depth_src = pot.lot_depth_source
        lines.append(f"    Area:             {_fmt(pot.lot_area_sf, ',.0f', suffix=' sf')} [{area_src}]")
        lines.append(f"    Width:            {_fmt(pot.lot_width_ft, '.1f', suffix=' ft')} [{width_src}]")
        lines.append(f"    Depth:            {_fmt(pot.lot_depth_ft, '.1f', suffix=' ft')} [{depth_src}]")

        cfg = r.stage1_config_used
        if cfg:
            zd = cfg.get('district_code', '?')
            lines.append("")
            lines.append(f"  Zoning Standards ({zd} from config/residential_districts.json):")
            min_lot = cfg.get('min_lot_area_sf')
            min_width = cfg.get('min_lot_width_ft')
            if min_lot and pot.lot_area_sf:
                conf_area = "CONFORMING" if pot.lot_area_sf >= min_lot else "NONCONFORMING"
                cmp = ">=" if pot.lot_area_sf >= min_lot else "<"
                lines.append(
                    f"    Min lot area:     {min_lot:,} sf -> {conf_area} "
                    f"({pot.lot_area_sf:,.0f} {cmp} {min_lot:,})"
                )
            if min_width and pot.lot_width_ft:
                conf_width = "CONFORMING" if pot.lot_width_ft >= min_width else "NONCONFORMING"
                cmp = ">=" if pot.lot_width_ft >= min_width else "<"
                lines.append(
                    f"    Min lot width:    {min_width} ft -> {conf_width} "
                    f"({pot.lot_width_ft:.1f} {cmp} {min_width})"
                )
            lines.append(f"    Max height:       {cfg.get('max_height_ft', 'N/A')} ft")
            lines.append(f"    Max lot coverage: {cfg.get('max_lot_coverage_pct', 'N/A')}%")
            fp_pct = cfg.get('max_building_footprint_pct')
            fp_cap = cfg.get('max_building_footprint_sf')
            if fp_pct:
                lines.append(f"    Max footprint:    {fp_pct}% (cap {fp_cap:,} sf)" if fp_cap else f"    Max footprint:    {fp_pct}%")

        lines.append("")
        lines.append(f"  Conformance: {pot.conformance_status.upper()}")
        if pot.limiting_factors:
            lines.append(f"  Limiting factors: {', '.join(pot.limiting_factors)}")
        if pot.conformance_issues:
            for issue in pot.conformance_issues:
                lines.append(f"    - {issue}")
        lines.append(f"  Max footprint: {_fmt(pot.max_building_footprint_sf, ',.0f', suffix=' sf')}")
        lines.append(f"  Max dwelling units: {pot.max_dwelling_units}")

    # -- STAGE 2 --
    lines.append("")
    lines.append("STAGE 2: CURRENT BUILT")
    cur = r.stage2_current
    if cur:
        lines.append("  GFA Source Priority:")
        gfa_api = raw.get("grossFloorAreaSquareFeetQty")
        imp_val = raw.get("improvementValueAmt")
        rate = r.stage2_neighborhood_rate

        # Tier 1: Property API
        if gfa_api is not None and (isinstance(gfa_api, (int, float)) and gfa_api > 0):
            lines.append(f"    1. Property API (grossFloorAreaSquareFeetQty): {gfa_api:,.0f} sf -> USED")
        else:
            lines.append(f"    1. Property API (grossFloorAreaSquareFeetQty): {gfa_api} -> SKIP")

        # Tier 2: Improvement value estimate
        if cur.gfa_source == "estimated_from_improvement_value" and imp_val and rate:
            lines.append(
                f"    2. Improvement value estimate: ${imp_val:,.0f} / ${rate.median:,.0f}/sf "
                f"= {cur.gross_floor_area_sf:,.0f} sf -> USED"
            )
        elif cur.gfa_source == "property_api":
            lines.append("    2. Improvement value estimate: (not needed)")
        else:
            imp_str = f"${imp_val:,.0f}" if imp_val else "None"
            lines.append(f"    2. Improvement value estimate: imp={imp_str} -> SKIP")

        # Tier 3: Not available
        if cur.gfa_source == "building_detected_no_gfa_data":
            lines.append(f"    3. Building detected but no GFA data available")
        elif cur.gfa_source == "not_available":
            lines.append(f"    3. No building / vacant")

        lines.append("")
        lines.append(f"  Current GFA:        {_fmt(cur.gross_floor_area_sf, ',.0f', suffix=' sf')} ({cur.gfa_source})")
        lines.append(f"  Stories:            {_fmt(cur.story_count)}")
        lines.append(f"  Year built:         {_fmt(cur.year_built)}")
        lines.append(f"  Dwelling units:     {_fmt(cur.dwelling_units)}")
        if cur.estimated_footprint_sf:
            if cur.story_count and cur.story_count > 0 and cur.gross_floor_area_sf:
                lines.append(
                    f"  Est. footprint:     {cur.gross_floor_area_sf:,.0f} / {cur.story_count} "
                    f"= {cur.estimated_footprint_sf:,.0f} sf"
                )
            else:
                lines.append(f"  Est. footprint:     {cur.estimated_footprint_sf:,.0f} sf")

        lines.append("")
        lines.append("  Assessment:")
        lines.append(f"    Land value:       {_fmt(cur.land_value, ',.0f', prefix='$')}")
        lines.append(f"    Improvement:      {_fmt(cur.improvement_value, ',.0f', prefix='$')}")
        lines.append(f"    Total:            {_fmt(cur.total_assessed_value, ',.0f', prefix='$')}")

        if rate:
            lines.append("")
            lines.append("  Neighborhood Calibration:")
            lines.append(f"    Median rate:      ${rate.median:,.0f}/sf (n={rate.sample_size})")
            lines.append(f"    Range:            ${rate.low:,.0f} - ${rate.high:,.0f}/sf")
            lines.append(f"    Fallback used:    {'Yes' if rate.fallback_used else 'No'}")

    # -- STAGE 3 --
    lines.append("")
    lines.append("STAGE 3: AVAILABLE RIGHTS")
    rts = r.stage3_rights
    if rts:
        if not rts.is_analyzable:
            lines.append("  Not analyzable:")
            for err in rts.analysis_errors:
                lines.append(f"    - {err}")
            for note in rts.notes:
                lines.append(f"    - {note}")
        else:
            fp = r.stage1_potential.max_building_footprint_sf if r.stage1_potential else None
            lines.append(f"  Max GFA:            {_fmt(rts.max_gfa_sf, ',.0f', suffix=' sf')}")
            if fp and rts.max_gfa_sf:
                lines.append(f"                      ({fp:,.0f} sf footprint x {DEFAULT_ASSUMED_STORIES} stories)")
            lines.append(f"  Current GFA:        {_fmt(rts.current_gfa_sf, ',.0f', suffix=' sf')}")
            lines.append(f"  Available GFA:      {_fmt(rts.available_gfa_sf, ',.0f', suffix=' sf')}")
            if rts.max_gfa_sf and rts.current_gfa_sf is not None and rts.available_gfa_sf is not None:
                lines.append(
                    f"                      ({rts.max_gfa_sf:,.0f} - {rts.current_gfa_sf:,.0f} "
                    f"= {rts.available_gfa_sf:,.0f})"
                )

            _tdr_labels = {
                "full": "FULL (vacant lot)",
                "substantial": "SUBSTANTIAL (< 80% utilized)",
                "limited": "LIMITED (80–100% utilized)",
                "none": "NONE (> 100%; nonconforming)",
            }
            tdr_label = _tdr_labels.get(rts.tdr_potential or "", "Unknown")
            lines.append("")
            lines.append(f"  TDR Potential:      {tdr_label}")
            lines.append(f"  Utilization:        {_fmt(rts.gfa_utilization_pct, '.1f', suffix='%')}")

            lines.append("")
            lines.append(f"  Available footprint: {_fmt(rts.available_footprint_sf, ',.0f', suffix=' sf')}")
            lines.append(f"  Available units:     {_fmt(rts.available_dwelling_units)}")

    # -- STAGE 4 --
    lines.append("")
    lines.append("STAGE 4: VALUATION")
    val = r.stage4_valuation
    if val:
        if not val.is_valueable:
            lines.append("  Not valueable:")
            for note in val.notes:
                lines.append(f"    - {note}")
        else:
            lines.append("  Inputs:")
            lines.append(f"    Available GFA:    {_fmt(val.available_gfa_sf, ',.0f', suffix=' sf')}")
            lines.append(f"    Available units:  {_fmt(val.available_dwelling_units)}")
            lines.append(f"    Land value:       {_fmt(val.assessed_land_value, ',.0f', prefix='$')}")
            lines.append(f"    Max GFA:          {_fmt(val.max_gfa_sf, ',.0f', suffix=' sf')}")

            lines.append("")
            _format_method(lines, "Method 1 - Land Residual", val.land_residual)
            lines.append("")
            _format_method(lines, "Method 2 - Assessment Ratio", val.assessment_ratio)
            lines.append("")
            _format_method(lines, "Method 3 - Price Per SF", val.price_per_sf)
            lines.append("")
            _format_method(lines, "Method 4 - Price Per Unit", val.price_per_unit)

            if val.estimated_value_low is not None and val.estimated_value_high is not None:
                lines.append("")
                lines.append("  Composite Range:")
                lines.append(f"    Low:  ${val.estimated_value_low:,.0f}")
                lines.append(f"    High: ${val.estimated_value_high:,.0f}")

            lines.append("")
            lines.append(f"  Confidence: {val.confidence.value.upper()}")
            for factor in val.confidence_factors:
                lines.append(f"    - {factor}")

    lines.append("")
    lines.append(sep)

    return "\n".join(lines)


def _format_method(lines: list[str], label: str, method: ValuationMethodResult | None) -> None:
    """Append formatted valuation method details to lines."""
    lines.append(f"  {label}:")
    if method is None or not method.is_applicable:
        reason = method.notes[0] if method and method.notes else "Not applicable"
        lines.append(f"    -> NOT APPLICABLE ({reason})")
        return

    lines.append(f"    Low:  ${method.low_estimate:,.0f}")
    lines.append(f"    High: ${method.high_estimate:,.0f}")
    for note in method.notes:
        lines.append(f"    ({note})")
    lines.append(f"    -> APPLICABLE")
