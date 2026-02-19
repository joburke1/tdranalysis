"""
Sales Price Range Estimation: Development Potential

Estimates the monetary value of a parcel's unused development rights
by applying four independent valuation methods and combining them into
a LOW/HIGH price range.

    Estimated Value = f(available rights, assessed land value, market parameters)

This module is intended for Transfer of Development Rights (TDR) policy
analysis. Results are estimates, NOT appraisals.

Valuation methods:
  1. Land Residual:     Derive land $/sf from assessed value, apply to available GFA
  2. Assessment Ratio:  Scale assessed land value by availability fraction and market ratio
  3. Price Per SF:      Apply configurable $/sf range to available GFA
  4. Price Per Unit:    Apply configurable $/unit range to available dwelling units

The composite price range is the envelope (min low, max high) of all applicable methods.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from .available_rights import (
    AvailableRightsResult,
    calculate_available_rights,
    DEFAULT_ASSUMED_STORIES,
)
from .current_built import (
    CurrentBuiltResult,
    NeighborhoodRate,
    analyze_current_built,
    estimate_neighborhood_improvement_rate,
)
from .development_potential import DevelopmentPotentialAnalyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ValuationParams:
    """
    Market parameters for development potential valuation.

    Loaded from config/valuation_params.json. All dollar values must be
    calibrated to current market conditions before use in policy analysis.
    """

    market_to_assessment_ratio_low: float
    """Low-end market-to-assessment ratio (e.g. 1.0 = market equals assessment)"""

    market_to_assessment_ratio_high: float
    """High-end market-to-assessment ratio (e.g. 1.15 = 15% above assessment)"""

    price_per_gfa_sf_low: float
    """Low-end price per sq ft of available GFA capacity (dollars)"""

    price_per_gfa_sf_high: float
    """High-end price per sq ft of available GFA capacity (dollars)"""

    price_per_unit_low: float
    """Low-end price per available dwelling unit (dollars)"""

    price_per_unit_high: float
    """High-end price per available dwelling unit (dollars)"""

    land_residual_discount_low: float
    """Conservative discount applied to raw land rate (0.0–1.0)"""

    land_residual_discount_high: float
    """Aggressive discount applied to raw land rate (0.0–1.0)"""

    high_confidence_min_land_value: float
    """Minimum assessed land value (dollars) for HIGH confidence rating"""

    high_confidence_min_available_gfa_sf: float
    """Minimum available GFA (sq ft) for HIGH confidence rating"""

    residential_improvement_value_per_sf: float = 185.0
    """$/SF used to estimate residential GFA from improvement value when the
    property API does not report floor area (typical for single-family homes)."""

    params_last_updated: str = ""
    """ISO date when these parameters were last calibrated"""


def load_valuation_params(config_dir: str | Path = "config") -> ValuationParams:
    """
    Load valuation parameters from config/valuation_params.json.

    Args:
        config_dir: Directory containing valuation_params.json

    Returns:
        ValuationParams with loaded market parameters

    Raises:
        FileNotFoundError: If valuation_params.json does not exist
        KeyError: If required fields are missing from the config file
    """
    config_path = Path(config_dir) / "valuation_params.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Valuation parameters config not found: {config_path}. "
            "Create config/valuation_params.json from the project template."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("_metadata", {})

    return ValuationParams(
        market_to_assessment_ratio_low=data["market_to_assessment_ratio"]["low"],
        market_to_assessment_ratio_high=data["market_to_assessment_ratio"]["high"],
        price_per_gfa_sf_low=data["price_per_available_gfa_sf"]["low"],
        price_per_gfa_sf_high=data["price_per_available_gfa_sf"]["high"],
        price_per_unit_low=data["price_per_available_dwelling_unit"]["low"],
        price_per_unit_high=data["price_per_available_dwelling_unit"]["high"],
        land_residual_discount_low=data["land_residual_discount_factor"]["low"],
        land_residual_discount_high=data["land_residual_discount_factor"]["high"],
        high_confidence_min_land_value=data["confidence_thresholds"]["high_confidence_min_land_value"],
        high_confidence_min_available_gfa_sf=data["confidence_thresholds"]["high_confidence_min_available_gfa_sf"],
        residential_improvement_value_per_sf=data.get("residential_improvement_value_per_sf", {}).get("fallback_value",
            data.get("residential_improvement_value_per_sf", {}).get("value", 185.0)),
        params_last_updated=meta.get("last_updated", ""),
    )


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

class ConfidenceLevel(str, Enum):
    """Reliability of the valuation estimate."""

    HIGH = "high"
    """3+ methods applicable, assessed land value and available GFA meet quality thresholds."""

    MEDIUM = "medium"
    """2 methods applicable, or data quality is below the HIGH threshold."""

    LOW = "low"
    """Only 1 method applicable, or key inputs (land value, GFA) are missing."""

    NOT_APPLICABLE = "not_applicable"
    """No applicable methods, parcel is overdeveloped, or has no available rights."""


@dataclass
class ValuationMethodResult:
    """Result from a single valuation method."""

    method_name: str
    """Short identifier for this method"""

    is_applicable: bool = False
    """Whether this method produced an estimate (sufficient data)"""

    low_estimate: Optional[float] = None
    """Low-end price estimate in dollars"""

    high_estimate: Optional[float] = None
    """High-end price estimate in dollars"""

    notes: list[str] = field(default_factory=list)
    """Method-specific notes and assumptions"""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValuationResult:
    """
    Estimated sales price range of a parcel's development potential.

    Combines four valuation methods into a composite LOW/HIGH price range.
    Includes a confidence indicator reflecting data quality and method coverage.

    DISCLAIMER: This is an estimate for policy analysis only, not a property
    appraisal or formal valuation. Calibrate market parameters to current
    conditions before use.
    """

    # Parcel identification
    parcel_id: Optional[str] = None
    """Parcel identifier (RPC)"""

    zoning_district: Optional[str] = None
    """Zoning district code"""

    # Composite price range
    estimated_value_low: Optional[float] = None
    """Low end of estimated value range (dollars) — minimum of all applicable method lows"""

    estimated_value_high: Optional[float] = None
    """High end of estimated value range (dollars) — maximum of all applicable method highs"""

    # Per-method results
    land_residual: Optional[ValuationMethodResult] = None
    """Land residual method: derived land $/sf × available GFA × discount"""

    assessment_ratio: Optional[ValuationMethodResult] = None
    """Assessment ratio method: assessed land value × market ratio × availability fraction"""

    price_per_sf: Optional[ValuationMethodResult] = None
    """Price per SF method: configurable $/sf × available GFA"""

    price_per_unit: Optional[ValuationMethodResult] = None
    """Price per unit method: configurable $/unit × available dwelling units"""

    # Confidence
    confidence: ConfidenceLevel = ConfidenceLevel.NOT_APPLICABLE
    """Reliability of the estimate based on data quality and method coverage"""

    confidence_factors: list[str] = field(default_factory=list)
    """Explanation of what drove the confidence rating"""

    # Input summary (for traceability)
    available_gfa_sf: Optional[float] = None
    """Available GFA input used for estimation"""

    available_dwelling_units: Optional[int] = None
    """Available dwelling units input used for estimation"""

    assessed_land_value: Optional[float] = None
    """Assessed land value used as input"""

    max_gfa_sf: Optional[float] = None
    """Maximum allowable GFA used as input"""

    # Flags
    is_valueable: bool = False
    """True if parcel has positive available rights worth estimating"""

    # Metadata
    notes: list[str] = field(default_factory=list)
    """Additional notes and warnings"""

    analysis_errors: list[str] = field(default_factory=list)
    """Errors encountered during analysis"""

    def to_dict(self) -> dict:
        """
        Convert result to a flat dictionary suitable for GeoDataFrame columns.

        Per-method results are flattened as prefixed columns.
        List fields are joined as semicolon-separated strings.
        """
        d = {
            "parcel_id": self.parcel_id,
            "zoning_district": self.zoning_district,
            "estimated_value_low": self.estimated_value_low,
            "estimated_value_high": self.estimated_value_high,
            "valuation_confidence": self.confidence.value,
            "valuation_is_valueable": self.is_valueable,
            "valuation_available_gfa_sf": self.available_gfa_sf,
            "valuation_available_dwelling_units": self.available_dwelling_units,
            "valuation_assessed_land_value": self.assessed_land_value,
            "valuation_max_gfa_sf": self.max_gfa_sf,
            "valuation_confidence_factors": "; ".join(self.confidence_factors),
            "valuation_notes": "; ".join(self.notes),
        }

        for method_attr, prefix in (
            ("land_residual", "valuation_land_residual"),
            ("assessment_ratio", "valuation_assessment_ratio"),
            ("price_per_sf", "valuation_per_sf"),
            ("price_per_unit", "valuation_per_unit"),
        ):
            method: Optional[ValuationMethodResult] = getattr(self, method_attr)
            if method is not None:
                d[f"{prefix}_low"] = method.low_estimate
                d[f"{prefix}_high"] = method.high_estimate
                d[f"{prefix}_applicable"] = method.is_applicable
            else:
                d[f"{prefix}_low"] = None
                d[f"{prefix}_high"] = None
                d[f"{prefix}_applicable"] = False

        return d

    def summary(self) -> str:
        """Generate human-readable summary with disclaimer."""
        lines = [
            "Sales Price Range: Development Potential",
            "=" * 40,
            f"Parcel ID: {self.parcel_id or 'N/A'}",
            f"Zoning District: {self.zoning_district or 'N/A'}",
        ]

        if not self.is_valueable:
            lines.append("")
            lines.append("No development potential value to estimate:")
            for note in self.notes:
                lines.append(f"  - {note}")
            for error in self.analysis_errors:
                lines.append(f"  - ERROR: {error}")
            lines.extend(["", _DISCLAIMER])
            return "\n".join(lines)

        if self.estimated_value_low is not None and self.estimated_value_high is not None:
            lines.extend([
                "",
                f"Estimated Value Range: ${self.estimated_value_low:,.0f} – ${self.estimated_value_high:,.0f}",
                f"Confidence: {self.confidence.value.upper()}",
            ])
            if self.confidence_factors:
                for factor in self.confidence_factors:
                    lines.append(f"  ({factor})")

        lines.extend(["", "Valuation Methods:"])

        def _fmt_method(label: str, method: Optional[ValuationMethodResult]) -> str:
            if method is None or not method.is_applicable:
                return f"  {label:<22} N/A"
            return (
                f"  {label:<22} ${method.low_estimate:>10,.0f} – "
                f"${method.high_estimate:>10,.0f}"
            )

        lines.append(_fmt_method("Land Residual:", self.land_residual))
        lines.append(_fmt_method("Assessment Ratio:", self.assessment_ratio))
        lines.append(_fmt_method("Price Per SF:", self.price_per_sf))
        lines.append(_fmt_method("Price Per Unit:", self.price_per_unit))

        lines.extend(["", "Input Data:"])
        if self.assessed_land_value is not None:
            lines.append(f"  Assessed Land Value:   ${self.assessed_land_value:,.0f}")
        else:
            lines.append("  Assessed Land Value:   N/A")
        if self.available_gfa_sf is not None:
            lines.append(f"  Available GFA:         {self.available_gfa_sf:,.0f} sf")
        if self.available_dwelling_units is not None:
            lines.append(f"  Available Units:       {self.available_dwelling_units}")

        if self.notes:
            lines.extend(["", "Notes:"])
            for note in self.notes:
                lines.append(f"  - {note}")

        lines.extend(["", _DISCLAIMER])
        return "\n".join(lines)


_DISCLAIMER = (
    "DISCLAIMER: This is an estimate for policy analysis only, not a property\n"
    "appraisal or formal valuation. Calibrate market parameters to current\n"
    "conditions before use."
)


# ---------------------------------------------------------------------------
# Private valuation method functions
# ---------------------------------------------------------------------------

def _land_residual_method(
    land_value: Optional[float],
    max_gfa_sf: Optional[float],
    available_gfa_sf: Optional[float],
    params: ValuationParams,
) -> ValuationMethodResult:
    """
    Land Residual Method: derive land $/sf from assessed value, apply to available GFA.

    land_rate = assessed_land_value / max_gfa_sf
    estimate  = available_gfa_sf × land_rate × discount_factor
    """
    if not land_value or land_value <= 0:
        return ValuationMethodResult(
            method_name="land_residual",
            is_applicable=False,
            notes=["Requires assessed land value"],
        )
    if not max_gfa_sf or max_gfa_sf <= 0:
        return ValuationMethodResult(
            method_name="land_residual",
            is_applicable=False,
            notes=["Max GFA is zero or unknown; cannot derive land rate"],
        )
    if not available_gfa_sf or available_gfa_sf <= 0:
        return ValuationMethodResult(
            method_name="land_residual",
            is_applicable=False,
            notes=["No available GFA capacity"],
        )

    land_rate = land_value / max_gfa_sf
    low = available_gfa_sf * land_rate * params.land_residual_discount_low
    high = available_gfa_sf * land_rate * params.land_residual_discount_high

    return ValuationMethodResult(
        method_name="land_residual",
        is_applicable=True,
        low_estimate=low,
        high_estimate=high,
        notes=[
            f"Derived land rate: ${land_rate:.2f}/sf of max buildable GFA",
            f"Discount factors applied: "
            f"{params.land_residual_discount_low:.0%}–{params.land_residual_discount_high:.0%}",
        ],
    )


def _assessment_ratio_method(
    land_value: Optional[float],
    max_gfa_sf: Optional[float],
    available_gfa_sf: Optional[float],
    params: ValuationParams,
) -> ValuationMethodResult:
    """
    Assessment Ratio Method: scale assessed land value by availability fraction and market ratio.

    available_fraction = available_gfa_sf / max_gfa_sf
    estimate = assessed_land_value × market_ratio × available_fraction
    """
    if not land_value or land_value <= 0:
        return ValuationMethodResult(
            method_name="assessment_ratio",
            is_applicable=False,
            notes=["Requires assessed land value"],
        )
    if not max_gfa_sf or max_gfa_sf <= 0:
        return ValuationMethodResult(
            method_name="assessment_ratio",
            is_applicable=False,
            notes=["Max GFA is zero or unknown; cannot compute availability fraction"],
        )
    if not available_gfa_sf or available_gfa_sf <= 0:
        return ValuationMethodResult(
            method_name="assessment_ratio",
            is_applicable=False,
            notes=["No available GFA capacity"],
        )

    # Cap fraction at 1.0 to handle minor data inconsistencies
    available_fraction = min(available_gfa_sf / max_gfa_sf, 1.0)
    low = land_value * params.market_to_assessment_ratio_low * available_fraction
    high = land_value * params.market_to_assessment_ratio_high * available_fraction

    return ValuationMethodResult(
        method_name="assessment_ratio",
        is_applicable=True,
        low_estimate=low,
        high_estimate=high,
        notes=[
            f"Available GFA fraction: {available_fraction:.1%} of max capacity",
            f"Market-to-assessment ratio: "
            f"{params.market_to_assessment_ratio_low:.2f}–{params.market_to_assessment_ratio_high:.2f}x",
        ],
    )


def _price_per_sf_method(
    available_gfa_sf: Optional[float],
    params: ValuationParams,
) -> ValuationMethodResult:
    """
    Price Per SF Method: apply configurable $/sf range to available GFA.

    estimate = available_gfa_sf × $/sf
    """
    if not available_gfa_sf or available_gfa_sf <= 0:
        return ValuationMethodResult(
            method_name="price_per_sf",
            is_applicable=False,
            notes=["No available GFA capacity"],
        )

    low = available_gfa_sf * params.price_per_gfa_sf_low
    high = available_gfa_sf * params.price_per_gfa_sf_high

    return ValuationMethodResult(
        method_name="price_per_sf",
        is_applicable=True,
        low_estimate=low,
        high_estimate=high,
        notes=[
            f"Applied ${params.price_per_gfa_sf_low:.0f}–${params.price_per_gfa_sf_high:.0f}/sf "
            f"to {available_gfa_sf:,.0f} sf of available GFA",
        ],
    )


def _price_per_unit_method(
    available_dwelling_units: Optional[int],
    params: ValuationParams,
) -> ValuationMethodResult:
    """
    Price Per Unit Method: apply configurable $/unit range to available dwelling units.

    estimate = available_dwelling_units × $/unit
    """
    if not available_dwelling_units or available_dwelling_units <= 0:
        return ValuationMethodResult(
            method_name="price_per_unit",
            is_applicable=False,
            notes=["No available dwelling unit capacity"],
        )

    low = available_dwelling_units * params.price_per_unit_low
    high = available_dwelling_units * params.price_per_unit_high

    return ValuationMethodResult(
        method_name="price_per_unit",
        is_applicable=True,
        low_estimate=low,
        high_estimate=high,
        notes=[
            f"Applied ${params.price_per_unit_low:,.0f}–${params.price_per_unit_high:,.0f}/unit "
            f"to {available_dwelling_units} available unit(s)",
        ],
    )


def _determine_confidence(
    applicable_methods: list[ValuationMethodResult],
    land_value: Optional[float],
    available_gfa_sf: Optional[float],
    params: ValuationParams,
) -> tuple[ConfidenceLevel, list[str]]:
    """Determine confidence level based on method coverage and data quality."""
    n = len(applicable_methods)

    if n == 0:
        return ConfidenceLevel.NOT_APPLICABLE, ["No applicable valuation methods"]

    has_good_land_value = (
        land_value is not None
        and land_value >= params.high_confidence_min_land_value
    )
    has_good_gfa = (
        available_gfa_sf is not None
        and available_gfa_sf >= params.high_confidence_min_available_gfa_sf
    )

    factors = []

    if n >= 3 and has_good_land_value and has_good_gfa:
        factors.append(f"{n} of 4 valuation methods applicable")
        factors.append(
            "Assessed land value and available GFA meet quality thresholds"
        )
        return ConfidenceLevel.HIGH, factors

    if n >= 2:
        factors.append(f"{n} of 4 valuation methods applicable")
        if not has_good_land_value:
            factors.append(
                f"Assessed land value below threshold "
                f"(${params.high_confidence_min_land_value:,.0f})"
            )
        if not has_good_gfa:
            factors.append(
                f"Available GFA below threshold "
                f"({params.high_confidence_min_available_gfa_sf:,.0f} sf)"
            )
        return ConfidenceLevel.MEDIUM, factors

    # n == 1
    factors.append(f"Only {n} of 4 valuation methods applicable")
    if not has_good_land_value:
        factors.append("Assessed land value unavailable or below threshold")
    if not has_good_gfa:
        factors.append(
            f"Available GFA below threshold "
            f"({params.high_confidence_min_available_gfa_sf:,.0f} sf)"
        )
    return ConfidenceLevel.LOW, factors


# ---------------------------------------------------------------------------
# Main calculation function
# ---------------------------------------------------------------------------

def calculate_valuation(
    rights: AvailableRightsResult,
    params: ValuationParams,
) -> ValuationResult:
    """
    Estimate the sales price range of a parcel's development potential.

    Applies four valuation methods to the available development rights and
    combines them into a composite LOW/HIGH price range.

    Args:
        rights: Available development rights result for the parcel.
                Must have rights.current populated with assessment data
                for assessment-based methods to be applicable.
        params: Market parameters loaded from valuation_params.json

    Returns:
        ValuationResult with composite price range and per-method results
    """
    result = ValuationResult(
        parcel_id=rights.parcel_id,
        zoning_district=rights.zoning_district,
    )

    # Extract inputs
    available_gfa_sf = rights.available_gfa_sf
    available_dwelling_units = rights.available_dwelling_units
    max_gfa_sf = rights.max_gfa_sf
    land_value = rights.current.land_value if rights.current is not None else None

    result.available_gfa_sf = available_gfa_sf
    result.available_dwelling_units = available_dwelling_units
    result.assessed_land_value = land_value
    result.max_gfa_sf = max_gfa_sf

    # Early exit: not enough data to analyze
    if not rights.is_analyzable:
        result.confidence = ConfidenceLevel.NOT_APPLICABLE
        result.notes.append(
            "Cannot estimate value: available rights analysis is incomplete"
        )
        result.notes.extend(rights.notes)
        result.analysis_errors.extend(rights.analysis_errors)
        return result

    # Early exit: overdeveloped — no unused development capacity
    if rights.is_overdeveloped:
        result.confidence = ConfidenceLevel.NOT_APPLICABLE
        result.is_valueable = False
        result.notes.append(
            "Parcel is overdeveloped (current building exceeds by-right zoning limits); "
            "no additional development potential to value"
        )
        return result

    # Check if there are any available rights at all
    has_available_gfa = available_gfa_sf is not None and available_gfa_sf > 0
    has_available_units = (
        available_dwelling_units is not None and available_dwelling_units > 0
    )

    if not has_available_gfa and not has_available_units:
        result.confidence = ConfidenceLevel.NOT_APPLICABLE
        result.is_valueable = False
        result.notes.append("No available development rights to value")
        return result

    result.is_valueable = True

    # Run all four methods independently
    result.land_residual = _land_residual_method(
        land_value, max_gfa_sf, available_gfa_sf, params
    )
    result.assessment_ratio = _assessment_ratio_method(
        land_value, max_gfa_sf, available_gfa_sf, params
    )
    result.price_per_sf = _price_per_sf_method(available_gfa_sf, params)
    result.price_per_unit = _price_per_unit_method(available_dwelling_units, params)

    # Collect applicable methods
    all_methods = [
        result.land_residual,
        result.assessment_ratio,
        result.price_per_sf,
        result.price_per_unit,
    ]
    applicable = [m for m in all_methods if m.is_applicable]

    if not applicable:
        result.confidence = ConfidenceLevel.NOT_APPLICABLE
        result.notes.append(
            "No valuation methods produced applicable results; "
            "check input data quality"
        )
        return result

    # Composite range: envelope of all applicable method estimates
    lows = [m.low_estimate for m in applicable if m.low_estimate is not None]
    highs = [m.high_estimate for m in applicable if m.high_estimate is not None]
    if lows:
        result.estimated_value_low = min(lows)
    if highs:
        result.estimated_value_high = max(highs)

    # Determine confidence
    result.confidence, result.confidence_factors = _determine_confidence(
        applicable, land_value, available_gfa_sf, params
    )

    return result


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------

def estimate_valuation_by_id(
    parcel_id: str,
    parcels_gdf: gpd.GeoDataFrame,
    parcel_id_column: str = "RPC",
    zoning_column: str = "zoning_district",
    config_dir: str | Path = "config",
    assumed_stories: float = DEFAULT_ASSUMED_STORIES,
) -> ValuationResult:
    """
    Estimate development potential value for a parcel by its ID.

    Runs the full pipeline: development potential → current built →
    available rights → valuation.

    Args:
        parcel_id: Parcel identifier to look up
        parcels_gdf: Enriched GeoDataFrame with zoning and property data
        parcel_id_column: Name of column containing parcel IDs
        zoning_column: Name of column containing zoning district codes
        config_dir: Directory containing zoning rules and valuation config
        assumed_stories: Stories to assume for max GFA estimate

    Returns:
        ValuationResult with estimated price range

    Raises:
        ValueError: If parcel ID not found
    """
    from .available_rights import analyze_available_rights_by_id

    rights = analyze_available_rights_by_id(
        parcel_id=parcel_id,
        parcels_gdf=parcels_gdf,
        parcel_id_column=parcel_id_column,
        zoning_column=zoning_column,
        config_dir=config_dir,
        assumed_stories=assumed_stories,
    )

    params = load_valuation_params(config_dir)
    return calculate_valuation(rights, params)


def estimate_valuation_geodataframe(
    gdf: gpd.GeoDataFrame,
    parcel_id_column: str = "RPC",
    zoning_column: str = "zoning_district",
    config_dir: str | Path = "config",
    assumed_stories: float = DEFAULT_ASSUMED_STORIES,
    analysis_year: int = 2026,
) -> gpd.GeoDataFrame:
    """
    Estimate development potential value for all parcels in a GeoDataFrame.

    Adds valuation columns to the GeoDataFrame. Internally runs the full
    analysis pipeline (development potential → current built → available
    rights → valuation) for each parcel.

    Before processing individual parcels, derives a neighborhood-specific
    improvement value per SF rate from recently-built homes (last 10 years).
    This replaces the static $185/SF fallback when sufficient data exists.

    Args:
        gdf: Enriched GeoDataFrame with zoning and property data
        parcel_id_column: Column with parcel IDs
        zoning_column: Column with zoning district codes
        config_dir: Directory containing zoning rules and valuation config
        assumed_stories: Stories to assume for max GFA estimate
        analysis_year: Current year for lookback calculation

    Returns:
        GeoDataFrame with added valuation columns
    """
    analyzer = DevelopmentPotentialAnalyzer(config_dir=config_dir)
    params = load_valuation_params(config_dir)

    # Derive neighborhood improvement $/SF from recent construction
    neighborhood_rate = estimate_neighborhood_improvement_rate(
        gdf,
        config_dir=config_dir,
        analysis_year=analysis_year,
        assumed_stories=assumed_stories,
        fallback_rate=params.residential_improvement_value_per_sf,
    )
    improvement_value_per_sf = neighborhood_rate.median

    records = []
    for idx, row in gdf.iterrows():
        parcel_id = row.get(parcel_id_column) if parcel_id_column else str(idx)
        zoning = row.get(zoning_column)
        is_split = row.get("is_split_zoned", False)

        if zoning is None:
            records.append(_empty_valuation_record())
            continue

        try:
            potential = analyzer.analyze(
                geometry=row.geometry,
                zoning_district=zoning,
                parcel_id=parcel_id,
                is_split_zoned=is_split,
            )
        except Exception as e:
            logger.warning(f"Error analyzing potential for {parcel_id}: {e}")
            records.append(_empty_valuation_record())
            continue

        current = analyze_current_built(
            row,
            parcel_id_column=parcel_id_column,
            improvement_value_per_sf=improvement_value_per_sf,
        )
        rights = calculate_available_rights(potential, current, assumed_stories)
        valuation = calculate_valuation(rights, params)

        record = {k: v for k, v in valuation.to_dict().items()
                  if k not in ("parcel_id", "zoning_district")}

        # Expose key intermediate fields from potential, current, and rights
        record.update(_intermediate_fields(potential, current, rights))

        # Attach neighborhood rate metadata to every row
        record["neighborhood_imp_rate_median"] = neighborhood_rate.median
        record["neighborhood_imp_rate_low"] = neighborhood_rate.low
        record["neighborhood_imp_rate_high"] = neighborhood_rate.high
        record["neighborhood_imp_rate_sample"] = neighborhood_rate.sample_size

        records.append(record)

    results_df = pd.DataFrame(records)
    result_gdf = pd.concat(
        [gdf.reset_index(drop=True), results_df], axis=1
    )
    return gpd.GeoDataFrame(result_gdf, geometry="geometry", crs=gdf.crs)


def _intermediate_fields(
    potential: "DevelopmentPotentialResult",
    current: "CurrentBuiltResult",
    rights: "AvailableRightsResult",
) -> dict:
    """
    Extract key fields from intermediate analysis results for inclusion
    in the flat GeoDataFrame output.

    These fields are computed during the pipeline but not included in
    ValuationResult.to_dict(). Exposing them here allows the runner and
    downstream consumers to produce a complete, self-contained output.
    """
    return {
        # Lot geometry (from zoning analysis)
        "lot_area_sf": potential.lot_area_sf,
        "lot_width_ft": potential.lot_width_ft,
        "lot_depth_ft": potential.lot_depth_ft,
        "is_conforming": potential.is_conforming,
        "conformance_status": potential.conformance_status,
        # Max development standards (by-right)
        "max_height_ft": potential.max_height_ft,
        "max_footprint_sf": potential.max_building_footprint_sf,
        "max_lot_coverage_sf": potential.max_lot_coverage_sf,
        "max_dwelling_units": potential.max_dwelling_units,
        # Current building
        "current_gfa_sf": current.gross_floor_area_sf,
        "current_stories": current.story_count,
        "current_footprint_sf": current.estimated_footprint_sf,
        "year_built": current.year_built,
        "has_building": current.has_building,
        "gfa_source": current.gfa_source,
        # Available rights
        "available_footprint_sf": rights.available_footprint_sf,
        "available_dwelling_units": rights.available_dwelling_units,
        "gfa_utilization_pct": rights.gfa_utilization_pct,
        "is_vacant": rights.is_vacant,
        "is_underdeveloped": rights.is_underdeveloped,
        "is_overdeveloped": rights.is_overdeveloped,
    }


def _empty_valuation_record() -> dict:
    """Return an empty valuation record for parcels that cannot be analyzed."""
    return {
        # Valuation
        "estimated_value_low": None,
        "estimated_value_high": None,
        "valuation_confidence": ConfidenceLevel.NOT_APPLICABLE.value,
        "valuation_is_valueable": False,
        "valuation_available_gfa_sf": None,
        "valuation_available_dwelling_units": None,
        "valuation_assessed_land_value": None,
        "valuation_max_gfa_sf": None,
        "valuation_confidence_factors": "",
        "valuation_notes": "",
        "valuation_land_residual_low": None,
        "valuation_land_residual_high": None,
        "valuation_land_residual_applicable": False,
        "valuation_assessment_ratio_low": None,
        "valuation_assessment_ratio_high": None,
        "valuation_assessment_ratio_applicable": False,
        "valuation_per_sf_low": None,
        "valuation_per_sf_high": None,
        "valuation_per_sf_applicable": False,
        "valuation_per_unit_low": None,
        "valuation_per_unit_high": None,
        "valuation_per_unit_applicable": False,
        # Intermediate fields
        "lot_area_sf": None,
        "lot_width_ft": None,
        "lot_depth_ft": None,
        "is_conforming": None,
        "conformance_status": None,
        "max_height_ft": None,
        "max_footprint_sf": None,
        "max_lot_coverage_sf": None,
        "max_dwelling_units": None,
        "current_gfa_sf": None,
        "current_stories": None,
        "current_footprint_sf": None,
        "year_built": None,
        "has_building": None,
        "gfa_source": None,
        "available_footprint_sf": None,
        "available_dwelling_units": None,
        "gfa_utilization_pct": None,
        "is_vacant": None,
        "is_underdeveloped": None,
        "is_overdeveloped": None,
        # Neighborhood rate
        "neighborhood_imp_rate_median": None,
        "neighborhood_imp_rate_low": None,
        "neighborhood_imp_rate_high": None,
        "neighborhood_imp_rate_sample": None,
    }
