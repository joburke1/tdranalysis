"""
Current Built Area Analysis

Extracts and summarizes what is currently built on a parcel using
property attribute data from the Arlington Open Data API.

Key fields used:
- grossFloorAreaSquareFeetQty: Total gross floor area (sq ft)
- storyHeightCnt: Number of stories
- numberOfUnitsCnt: Number of dwelling units
- propertyYearBuilt: Year the structure was built
- propertyClassTypeCode / propertyClassTypeDsc: Property classification
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CurrentBuiltResult:
    """
    Summary of what is currently built on a parcel.

    Populated from Arlington Open Data API property attributes
    joined to the parcel via Real Property Code (RPC).
    """

    # Parcel identification
    parcel_id: Optional[str] = None
    """Parcel identifier (RPC)"""

    # Building characteristics
    gross_floor_area_sf: Optional[float] = None
    """Gross floor area in square feet from county records"""

    story_count: Optional[float] = None
    """Number of stories"""

    year_built: Optional[int] = None
    """Year the structure was built"""

    dwelling_units: Optional[int] = None
    """Number of dwelling units"""

    # Property classification
    property_class_code: Optional[str] = None
    """County property class type code"""

    property_class_desc: Optional[str] = None
    """County property class type description"""

    # Flags
    is_commercial: Optional[bool] = None
    """Whether property has commercial indicator"""

    is_mixed_use: Optional[bool] = None
    """Whether property has mixed-use indicator"""

    # Derived metrics
    estimated_footprint_sf: Optional[float] = None
    """Estimated building footprint (gross_floor_area / stories)"""

    has_building: bool = False
    """Whether a building exists on the parcel"""

    gfa_source: Optional[str] = None
    """Source of the GFA figure: 'property_api', 'estimated_from_improvement_value', or 'not_available'"""

    # Assessment values
    improvement_value: Optional[float] = None
    """Assessed improvement (structure) value"""

    land_value: Optional[float] = None
    """Assessed land value"""

    total_assessed_value: Optional[float] = None
    """Total assessed value"""

    # Data quality
    data_available: bool = False
    """Whether property data was found for this parcel"""

    notes: list[str] = field(default_factory=list)
    """Additional notes and warnings"""

    def to_dict(self) -> dict:
        """Convert result to dictionary."""
        return asdict(self)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "Current Built Area Analysis",
            "=" * 40,
            f"Parcel ID: {self.parcel_id or 'N/A'}",
        ]

        if not self.data_available:
            lines.append("No property data available for this parcel.")
            return "\n".join(lines)

        lines.extend([
            "",
            "Building Characteristics:",
            f"  Gross Floor Area: {self.gross_floor_area_sf:,.0f} sf"
            if self.gross_floor_area_sf
            else "  Gross Floor Area: N/A",
            f"  Stories: {self.story_count}"
            if self.story_count
            else "  Stories: N/A",
            f"  Year Built: {self.year_built}"
            if self.year_built
            else "  Year Built: N/A",
            f"  Dwelling Units: {self.dwelling_units}"
            if self.dwelling_units
            else "  Dwelling Units: N/A",
            f"  Estimated Footprint: {self.estimated_footprint_sf:,.0f} sf"
            if self.estimated_footprint_sf
            else "  Estimated Footprint: N/A",
        ])

        lines.extend([
            "",
            "Classification:",
            f"  Type: {self.property_class_desc or self.property_class_code or 'N/A'}",
            f"  Commercial: {'Yes' if self.is_commercial else 'No'}",
            f"  Mixed Use: {'Yes' if self.is_mixed_use else 'No'}",
        ])

        if self.total_assessed_value is not None:
            lines.extend([
                "",
                "Assessment:",
                f"  Land: ${self.land_value:,.0f}" if self.land_value else "  Land: N/A",
                f"  Improvement: ${self.improvement_value:,.0f}" if self.improvement_value else "  Improvement: N/A",
                f"  Total: ${self.total_assessed_value:,.0f}",
            ])

        if self.notes:
            lines.extend(["", "Notes:"])
            for note in self.notes:
                lines.append(f"  - {note}")

        return "\n".join(lines)


_IMPROVEMENT_VALUE_THRESHOLD = 5_000.0
"""Minimum assessed improvement value (dollars) to infer a building exists."""


def analyze_current_built(
    parcel_row: pd.Series,
    parcel_id_column: str = "RPC",
    improvement_value_per_sf: float = 185.0,
) -> CurrentBuiltResult:
    """
    Analyze what is currently built on a single parcel.

    Expects a row from an enriched GeoDataFrame that has been through
    the processor pipeline (property and assessment data joined).

    GFA source priority:
      1. ``grossFloorAreaSquareFeetQty`` from the property API (when > 0)
      2. Estimated from ``improvementValueAmt`` ÷ ``improvement_value_per_sf``
         when the property API does not report floor area (typical for
         single-family residential in Arlington's dataset)
      3. Not available (``has_building = False``)

    Args:
        parcel_row: Series from an enriched GeoDataFrame
        parcel_id_column: Name of the parcel ID column
        improvement_value_per_sf: Assessed improvement value per square foot
            used to estimate GFA when the property API is silent. Default 185
            reflects typical Arlington residential assessments; calibrate from
            local sales data before use in policy analysis.

    Returns:
        CurrentBuiltResult summarizing existing development
    """
    result = CurrentBuiltResult()

    # Parcel ID
    result.parcel_id = _get_value(parcel_row, parcel_id_column)

    # Read all source fields up front so assessment values are available
    # even when the property join missed this parcel entirely.
    gfa = _get_numeric(parcel_row, "grossFloorAreaSquareFeetQty")
    stories = _get_numeric(parcel_row, "storyHeightCnt")
    year_built = _get_numeric(parcel_row, "propertyYearBuilt")
    units = _get_numeric(parcel_row, "numberOfUnitsCnt")
    improvement_value = _get_numeric(parcel_row, "improvementValueAmt")
    land_value = _get_numeric(parcel_row, "landValueAmt")
    total_value = _get_numeric(parcel_row, "totalValueAmt")

    has_property_data = not (gfa is None and stories is None and year_built is None)
    has_assessment_data = improvement_value is not None or land_value is not None

    if not has_property_data and not has_assessment_data:
        result.data_available = False
        result.notes.append("No property or assessment data joined to this parcel")
        return result

    result.data_available = True

    # Building characteristics from property API
    result.story_count = stories
    result.year_built = int(year_built) if year_built is not None else None
    result.dwelling_units = int(units) if units is not None else None

    # Classification
    result.property_class_code = _get_value(parcel_row, "propertyClassTypeCode")
    result.property_class_desc = _get_value(parcel_row, "propertyClassTypeDsc")
    result.is_commercial = _get_bool(parcel_row, "commercialInd")
    result.is_mixed_use = _get_bool(parcel_row, "mixedUseInd")

    # Assessment values
    result.improvement_value = improvement_value
    result.land_value = land_value
    result.total_assessed_value = total_value

    # GFA: prefer property API; fall back to improvement-value estimate.
    # Arlington's property API does not report GFA for single-family
    # residential, so the fallback is essential for that property class.
    if gfa is not None and gfa > 0:
        result.gross_floor_area_sf = gfa
        result.has_building = True
        result.gfa_source = "property_api"
    elif improvement_value is not None and improvement_value > _IMPROVEMENT_VALUE_THRESHOLD:
        estimated_gfa = round(improvement_value / improvement_value_per_sf)
        result.gross_floor_area_sf = float(estimated_gfa)
        result.has_building = True
        result.gfa_source = "estimated_from_improvement_value"
        result.notes.append(
            f"GFA estimated from assessed improvement value "
            f"(${improvement_value:,.0f} ÷ ${improvement_value_per_sf:.0f}/SF "
            f"= {estimated_gfa:,} SF)"
        )
    elif year_built is not None and year_built > 0:
        # Building confirmed by year-built record but no GFA can be estimated:
        # the assessment API returned no improvement value for this parcel.
        # Mark the building as present but exclude from available-rights and
        # valuation calculations — the results would be unreliable.
        result.has_building = True
        result.gfa_source = "building_detected_no_gfa_data"
        result.notes.append(
            f"Building confirmed (year built {int(year_built)}) but GFA cannot "
            "be estimated: assessment API returned no improvement value for this "
            "parcel. Excluded from available-rights and valuation calculations."
        )
    else:
        result.has_building = False
        result.gfa_source = "not_available"

    # Derived: estimated footprint
    effective_gfa = result.gross_floor_area_sf
    if effective_gfa and effective_gfa > 0:
        if stories is not None and stories > 0:
            result.estimated_footprint_sf = effective_gfa / stories
        else:
            result.estimated_footprint_sf = effective_gfa
            result.notes.append(
                "Story count unavailable; estimated footprint assumes single story"
            )

    return result


def analyze_current_built_by_id(
    parcel_id: str,
    parcels_gdf: gpd.GeoDataFrame,
    parcel_id_column: str = "RPC",
) -> CurrentBuiltResult:
    """
    Analyze current built area for a parcel by its ID.

    Args:
        parcel_id: Parcel identifier to look up
        parcels_gdf: Enriched GeoDataFrame with property data joined
        parcel_id_column: Name of column containing parcel IDs

    Returns:
        CurrentBuiltResult summarizing existing development

    Raises:
        ValueError: If parcel ID not found
    """
    mask = parcels_gdf[parcel_id_column] == parcel_id
    if not mask.any():
        raise ValueError(f"Parcel '{parcel_id}' not found in dataset")

    row = parcels_gdf.loc[mask].iloc[0]
    return analyze_current_built(row, parcel_id_column=parcel_id_column)


def analyze_current_built_geodataframe(
    gdf: gpd.GeoDataFrame,
    parcel_id_column: Optional[str] = None,
    improvement_value_per_sf: float = 185.0,
) -> gpd.GeoDataFrame:
    """
    Analyze current built area for all parcels in a GeoDataFrame.

    Adds current-built columns to the GeoDataFrame for use in
    available-rights calculations downstream.

    Args:
        gdf: Enriched GeoDataFrame with property data joined
        parcel_id_column: Optional column with parcel IDs
        improvement_value_per_sf: $/SF used to estimate GFA from improvement
            value when the property API does not report floor area.

    Returns:
        GeoDataFrame with added current-built analysis columns
    """
    records = []
    for idx, row in gdf.iterrows():
        result = analyze_current_built(
            row,
            parcel_id_column=parcel_id_column or "RPC",
            improvement_value_per_sf=improvement_value_per_sf,
        )
        records.append({
            "current_gfa_sf": result.gross_floor_area_sf,
            "current_stories": result.story_count,
            "current_dwelling_units": result.dwelling_units,
            "current_year_built": result.year_built,
            "current_estimated_footprint_sf": result.estimated_footprint_sf,
            "current_has_building": result.has_building,
            "current_improvement_value": result.improvement_value,
            "current_data_available": result.data_available,
        })

    results_df = pd.DataFrame(records)
    result_gdf = pd.concat(
        [gdf.reset_index(drop=True), results_df], axis=1
    )
    return gpd.GeoDataFrame(result_gdf, geometry="geometry", crs=gdf.crs)


# -- Helper functions for safe value extraction --

def _get_value(row: pd.Series, col: str) -> Optional[str]:
    """Get a string value from a row, returning None if missing."""
    if col not in row.index:
        return None
    val = row[col]
    if pd.isna(val):
        return None
    return str(val)


def _get_numeric(row: pd.Series, col: str) -> Optional[float]:
    """Get a numeric value from a row, returning None if missing."""
    if col not in row.index:
        return None
    val = row[col]
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_bool(row: pd.Series, col: str) -> Optional[bool]:
    """Get a boolean value from a row, returning None if missing."""
    if col not in row.index:
        return None
    val = row[col]
    if pd.isna(val):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "yes", "1", "y")
    return bool(val)
