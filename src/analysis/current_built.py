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
    """Whether a building exists on the parcel (gross floor area > 0)"""

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


def analyze_current_built(
    parcel_row: pd.Series,
    parcel_id_column: str = "RPC",
) -> CurrentBuiltResult:
    """
    Analyze what is currently built on a single parcel.

    Expects a row from an enriched GeoDataFrame that has been through
    the processor pipeline (property and assessment data joined).

    Args:
        parcel_row: Series from an enriched GeoDataFrame
        parcel_id_column: Name of the parcel ID column

    Returns:
        CurrentBuiltResult summarizing existing development
    """
    result = CurrentBuiltResult()

    # Parcel ID
    result.parcel_id = _get_value(parcel_row, parcel_id_column)

    # Check if property data was joined
    gfa = _get_numeric(parcel_row, "grossFloorAreaSquareFeetQty")
    stories = _get_numeric(parcel_row, "storyHeightCnt")
    year_built = _get_numeric(parcel_row, "propertyYearBuilt")
    units = _get_numeric(parcel_row, "numberOfUnitsCnt")

    # If none of the property fields are present, data wasn't joined
    if gfa is None and stories is None and year_built is None:
        result.data_available = False
        result.notes.append("No property data joined to this parcel")
        return result

    result.data_available = True

    # Building characteristics
    result.gross_floor_area_sf = gfa
    result.story_count = stories
    result.year_built = int(year_built) if year_built is not None else None
    result.dwelling_units = int(units) if units is not None else None

    # Classification
    result.property_class_code = _get_value(parcel_row, "propertyClassTypeCode")
    result.property_class_desc = _get_value(parcel_row, "propertyClassTypeDsc")
    result.is_commercial = _get_bool(parcel_row, "commercialInd")
    result.is_mixed_use = _get_bool(parcel_row, "mixedUseInd")

    # Assessment values
    result.improvement_value = _get_numeric(parcel_row, "improvementValueAmt")
    result.land_value = _get_numeric(parcel_row, "landValueAmt")
    result.total_assessed_value = _get_numeric(parcel_row, "totalValueAmt")

    # Derived: has_building
    result.has_building = gfa is not None and gfa > 0

    # Derived: estimated footprint
    if gfa is not None and gfa > 0 and stories is not None and stories > 0:
        result.estimated_footprint_sf = gfa / stories
    elif gfa is not None and gfa > 0:
        # If stories is missing, assume single story as conservative estimate
        result.estimated_footprint_sf = gfa
        result.notes.append(
            "Story count unavailable; estimated footprint assumes single story"
        )

    # Data quality warnings
    if gfa is not None and gfa == 0 and result.improvement_value and result.improvement_value > 0:
        result.notes.append(
            "Gross floor area is 0 but improvement value is positive; "
            "building data may be incomplete"
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
) -> gpd.GeoDataFrame:
    """
    Analyze current built area for all parcels in a GeoDataFrame.

    Adds current-built columns to the GeoDataFrame for use in
    available-rights calculations downstream.

    Args:
        gdf: Enriched GeoDataFrame with property data joined
        parcel_id_column: Optional column with parcel IDs

    Returns:
        GeoDataFrame with added current-built analysis columns
    """
    records = []
    for idx, row in gdf.iterrows():
        result = analyze_current_built(
            row,
            parcel_id_column=parcel_id_column or "RPC",
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
