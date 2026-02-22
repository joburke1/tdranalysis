"""
Available Development Rights Calculation

Computes remaining (unused) development rights for a parcel by comparing
maximum by-right development potential against what is currently built.

    Available Rights = Maximum Potential - Current Built

This is the core calculation for Transfer of Development Rights (TDR)
analysis: a parcel's available rights represent what could theoretically
be transferred to a receiving site.
"""

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from .development_potential import (
    DevelopmentPotentialResult,
    DevelopmentPotentialAnalyzer,
)
from .current_built import (
    CurrentBuiltResult,
    analyze_current_built,
)

logger = logging.getLogger(__name__)


@dataclass
class AvailableRightsResult:
    """
    Available (unused) development rights for a parcel.

    Computed as the difference between maximum by-right potential
    and current built area. Negative values indicate the existing
    building exceeds what current zoning would allow by-right
    (legal nonconforming use).
    """

    # Parcel identification
    parcel_id: Optional[str] = None
    """Parcel identifier (RPC)"""

    zoning_district: Optional[str] = None
    """Zoning district code"""

    # Maximum potential (from zoning analysis)
    max_gfa_sf: Optional[float] = None
    """Maximum gross floor area allowed by-right (footprint x stories)"""

    max_building_footprint_sf: Optional[float] = None
    """Maximum main building footprint allowed"""

    max_lot_coverage_sf: Optional[float] = None
    """Maximum lot coverage allowed"""

    max_dwelling_units: int = 0
    """Maximum dwelling units allowed by-right"""

    # Current built (from property data)
    current_gfa_sf: Optional[float] = None
    """Current gross floor area from county records"""

    current_estimated_footprint_sf: Optional[float] = None
    """Estimated current building footprint (GFA / stories)"""

    current_dwelling_units: Optional[int] = None
    """Current number of dwelling units"""

    # Available rights (max - current)
    available_gfa_sf: Optional[float] = None
    """Remaining GFA capacity (max - current). Negative = nonconforming."""

    available_footprint_sf: Optional[float] = None
    """Remaining footprint capacity. Negative = nonconforming."""

    available_lot_coverage_sf: Optional[float] = None
    """Remaining lot coverage capacity."""

    available_dwelling_units: Optional[int] = None
    """Remaining dwelling unit capacity."""

    # Utilization
    gfa_utilization_pct: Optional[float] = None
    """Percentage of max GFA currently used (current / max * 100)"""

    footprint_utilization_pct: Optional[float] = None
    """Percentage of max footprint currently used"""

    # Status flags
    is_underdeveloped: Optional[bool] = None
    """True if significant unused GFA capacity exists (utilization < 80%)"""

    is_overdeveloped: Optional[bool] = None
    """True if current GFA exceeds max allowed (legal nonconforming)"""

    is_vacant: Optional[bool] = None
    """True if no building exists on the parcel"""

    is_analyzable: bool = False
    """True if both max potential and current built data are available"""

    tdr_potential: Optional[str] = None
    """TDR potential classification: 'full' | 'substantial' | 'limited' | 'none'
    full        — vacant lot; all rights available
    substantial — GFA utilization < 80%; significant unused capacity
    limited     — GFA utilization 80–100%; substantially built out
    none        — GFA utilization > 100%; legal nonconforming use
    """

    # Component results
    potential: Optional[DevelopmentPotentialResult] = None
    """Full development potential analysis result"""

    current: Optional[CurrentBuiltResult] = None
    """Full current built area result"""

    # Metadata
    notes: list[str] = field(default_factory=list)
    """Additional notes and warnings"""

    analysis_errors: list[str] = field(default_factory=list)
    """Any errors encountered during analysis"""

    def to_dict(self) -> dict:
        """Convert result to dictionary (excludes nested component results)."""
        d = asdict(self)
        # Remove large nested objects for flat serialization
        d.pop("potential", None)
        d.pop("current", None)
        return d

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "Available Development Rights",
            "=" * 40,
            f"Parcel ID: {self.parcel_id or 'N/A'}",
            f"Zoning District: {self.zoning_district or 'N/A'}",
        ]

        if not self.is_analyzable:
            lines.append("")
            lines.append("Unable to compute available rights:")
            for error in self.analysis_errors:
                lines.append(f"  - {error}")
            for note in self.notes:
                lines.append(f"  - {note}")
            return "\n".join(lines)

        lines.extend([
            "",
            "Maximum Potential (By-Right):",
            f"  GFA: {self.max_gfa_sf:,.0f} sf" if self.max_gfa_sf else "  GFA: N/A",
            f"  Footprint: {self.max_building_footprint_sf:,.0f} sf"
            if self.max_building_footprint_sf
            else "  Footprint: N/A",
            f"  Dwelling Units: {self.max_dwelling_units}",
            "",
            "Currently Built:",
            f"  GFA: {self.current_gfa_sf:,.0f} sf"
            if self.current_gfa_sf is not None
            else "  GFA: N/A",
            f"  Est. Footprint: {self.current_estimated_footprint_sf:,.0f} sf"
            if self.current_estimated_footprint_sf
            else "  Est. Footprint: N/A",
            f"  Dwelling Units: {self.current_dwelling_units}"
            if self.current_dwelling_units is not None
            else "  Dwelling Units: N/A",
            "",
            "Available Rights:",
        ])

        if self.available_gfa_sf is not None:
            sign = "+" if self.available_gfa_sf >= 0 else ""
            lines.append(f"  GFA: {sign}{self.available_gfa_sf:,.0f} sf")
        if self.available_footprint_sf is not None:
            sign = "+" if self.available_footprint_sf >= 0 else ""
            lines.append(f"  Footprint: {sign}{self.available_footprint_sf:,.0f} sf")
        if self.available_dwelling_units is not None:
            sign = "+" if self.available_dwelling_units >= 0 else ""
            lines.append(f"  Dwelling Units: {sign}{self.available_dwelling_units}")

        if self.gfa_utilization_pct is not None:
            lines.extend([
                "",
                f"GFA Utilization: {self.gfa_utilization_pct:.1f}%",
            ])

        _tdr_labels = {
            "full": "FULL (vacant lot; all rights available)",
            "substantial": "SUBSTANTIAL (significant unused capacity)",
            "limited": "LIMITED (80–100% built out)",
            "none": "NONE (exceeds by-right limits; legal nonconforming)",
        }
        if self.tdr_potential:
            lines.append(
                f"TDR Potential: {_tdr_labels.get(self.tdr_potential, self.tdr_potential.upper())}"
            )

        if self.notes:
            lines.extend(["", "Notes:"])
            for note in self.notes:
                lines.append(f"  - {note}")

        return "\n".join(lines)


# Threshold for "underdeveloped" classification
UNDERDEVELOPED_THRESHOLD_PCT = 80.0

# Assumed stories for estimating max GFA from footprint
# R districts allow 35ft height; typical residential = 2-3 stories
DEFAULT_ASSUMED_STORIES = 2.5


def calculate_available_rights(
    potential: DevelopmentPotentialResult,
    current: CurrentBuiltResult,
    assumed_stories: float = DEFAULT_ASSUMED_STORIES,
) -> AvailableRightsResult:
    """
    Calculate available development rights for a parcel.

    Compares the maximum by-right development potential against
    what is currently built to determine remaining capacity.

    Args:
        potential: Maximum development potential result
        current: Current built area result
        assumed_stories: Number of stories to assume when estimating
            max GFA from footprint (default 2.5 for 35ft height limit)

    Returns:
        AvailableRightsResult with computed available rights
    """
    result = AvailableRightsResult(
        parcel_id=potential.parcel_id or current.parcel_id,
        zoning_district=potential.zoning_district,
        potential=potential,
        current=current,
    )

    # Check if we have enough data to compute
    if not potential.is_residential_zoning:
        result.notes.append("Parcel is not in a residential zoning district")
        return result

    if potential.analysis_errors:
        result.analysis_errors.extend(potential.analysis_errors)
        return result

    if not current.data_available:
        result.notes.append(
            "No property data available; cannot determine current built area"
        )
        # Still populate max values for reference
        result.max_building_footprint_sf = potential.max_building_footprint_sf
        result.max_lot_coverage_sf = potential.max_lot_coverage_sf
        result.max_dwelling_units = potential.max_dwelling_units
        if potential.max_building_footprint_sf:
            result.max_gfa_sf = potential.max_building_footprint_sf * assumed_stories
        return result

    result.is_analyzable = True

    # -- Maximum potential --
    result.max_building_footprint_sf = potential.max_building_footprint_sf
    result.max_lot_coverage_sf = potential.max_lot_coverage_sf
    result.max_dwelling_units = potential.max_dwelling_units

    # Estimate max GFA = footprint x assumed stories
    if potential.max_building_footprint_sf:
        result.max_gfa_sf = potential.max_building_footprint_sf * assumed_stories
        result.notes.append(
            f"Max GFA estimated as footprint x {assumed_stories} stories "
            f"(R districts use footprint limits, not FAR)"
        )

    # -- Current built --
    # If a building is confirmed via year_built but GFA cannot be estimated
    # (assessment API gap), treat the parcel as having a building but mark
    # it non-analyzable to avoid overstating available capacity.
    if current.has_building and current.gross_floor_area_sf is None:
        result.is_analyzable = False
        result.is_vacant = False
        result.current_dwelling_units = current.dwelling_units
        for note in current.notes:
            result.notes.append(note)
        result.analysis_errors.append(
            "Building confirmed but GFA not available; "
            "available-rights calculation skipped to avoid overstating capacity"
        )
        return result

    result.current_gfa_sf = current.gross_floor_area_sf or 0.0
    result.current_estimated_footprint_sf = current.estimated_footprint_sf
    result.current_dwelling_units = current.dwelling_units
    result.is_vacant = not current.has_building

    # -- Available rights (difference) --

    # GFA
    if result.max_gfa_sf is not None:
        result.available_gfa_sf = result.max_gfa_sf - result.current_gfa_sf

    # Footprint
    if (
        result.max_building_footprint_sf is not None
        and result.current_estimated_footprint_sf is not None
    ):
        result.available_footprint_sf = (
            result.max_building_footprint_sf - result.current_estimated_footprint_sf
        )

    # Lot coverage
    if result.max_lot_coverage_sf is not None:
        # We don't have actual lot coverage from property data, just footprint
        result.available_lot_coverage_sf = None
        result.notes.append(
            "Lot coverage availability not computed; actual impervious "
            "coverage data not available from property records"
        )

    # Dwelling units
    result.available_dwelling_units = (
        result.max_dwelling_units - (result.current_dwelling_units or 0)
    )

    # -- Utilization --
    if result.max_gfa_sf and result.max_gfa_sf > 0:
        result.gfa_utilization_pct = (
            result.current_gfa_sf / result.max_gfa_sf * 100.0
        )

    if (
        result.max_building_footprint_sf
        and result.max_building_footprint_sf > 0
        and result.current_estimated_footprint_sf is not None
    ):
        result.footprint_utilization_pct = (
            result.current_estimated_footprint_sf
            / result.max_building_footprint_sf
            * 100.0
        )

    # -- Status flags --
    if result.is_vacant:
        result.is_underdeveloped = True
        result.is_overdeveloped = False
    elif result.gfa_utilization_pct is not None:
        result.is_overdeveloped = result.gfa_utilization_pct > 100.0
        result.is_underdeveloped = (
            result.gfa_utilization_pct < UNDERDEVELOPED_THRESHOLD_PCT
        )
    else:
        result.is_underdeveloped = None
        result.is_overdeveloped = None

    # Warn about overdevelopment
    if result.is_overdeveloped:
        result.notes.append(
            "Current building exceeds by-right zoning limits; "
            "may be legal nonconforming (grandfathered) use"
        )

    # -- TDR Potential classification --
    if result.is_vacant:
        result.tdr_potential = "full"
    elif result.is_overdeveloped:
        result.tdr_potential = "none"
    elif result.is_underdeveloped:
        result.tdr_potential = "substantial"
    elif result.is_underdeveloped is not None:
        # Explicitly False: 80–100% utilization range
        result.tdr_potential = "limited"
    # else: remains None (utilization indeterminate; insufficient data)

    return result


def analyze_available_rights_by_id(
    parcel_id: str,
    parcels_gdf: gpd.GeoDataFrame,
    parcel_id_column: str = "RPC",
    zoning_column: str = "zoning_district",
    config_dir: str | Path = "config",
    assumed_stories: float = DEFAULT_ASSUMED_STORIES,
) -> AvailableRightsResult:
    """
    Analyze available development rights for a parcel by its ID.

    Runs both the development potential and current built analyses,
    then computes the difference.

    Args:
        parcel_id: Parcel identifier to look up
        parcels_gdf: Enriched GeoDataFrame with zoning and property data
        parcel_id_column: Name of column containing parcel IDs
        zoning_column: Name of column containing zoning district codes
        config_dir: Directory containing zoning rules configuration
        assumed_stories: Stories to assume for max GFA estimate

    Returns:
        AvailableRightsResult with computed available rights

    Raises:
        ValueError: If parcel ID not found
    """
    from .development_potential import analyze_parcel_by_id

    # Run development potential analysis
    potential = analyze_parcel_by_id(
        parcel_id=parcel_id,
        parcels_gdf=parcels_gdf,
        parcel_id_column=parcel_id_column,
        zoning_column=zoning_column,
        config_dir=config_dir,
    )

    # Run current built analysis
    mask = parcels_gdf[parcel_id_column] == parcel_id
    row = parcels_gdf.loc[mask].iloc[0]
    current = analyze_current_built(row, parcel_id_column=parcel_id_column)

    return calculate_available_rights(potential, current, assumed_stories)


def analyze_available_rights_geodataframe(
    gdf: gpd.GeoDataFrame,
    parcel_id_column: str = "RPC",
    zoning_column: str = "zoning_district",
    config_dir: str | Path = "config",
    assumed_stories: float = DEFAULT_ASSUMED_STORIES,
) -> gpd.GeoDataFrame:
    """
    Analyze available development rights for all parcels in a GeoDataFrame.

    Adds available-rights columns to the GeoDataFrame for bulk TDR analysis.

    Args:
        gdf: Enriched GeoDataFrame with zoning and property data
        parcel_id_column: Column with parcel IDs
        zoning_column: Column with zoning district codes
        config_dir: Directory containing zoning rules configuration
        assumed_stories: Stories to assume for max GFA estimate

    Returns:
        GeoDataFrame with added available-rights columns
    """
    analyzer = DevelopmentPotentialAnalyzer(config_dir=config_dir)

    records = []
    for idx, row in gdf.iterrows():
        parcel_id = row.get(parcel_id_column) if parcel_id_column else str(idx)
        zoning = row.get(zoning_column)
        is_split = row.get("is_split_zoned", False)

        # Development potential
        if zoning is None:
            records.append(_empty_rights_record())
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
            records.append(_empty_rights_record())
            continue

        # Current built
        current = analyze_current_built(row, parcel_id_column=parcel_id_column)

        # Available rights
        rights = calculate_available_rights(potential, current, assumed_stories)

        records.append({
            "max_gfa_sf": rights.max_gfa_sf,
            "current_gfa_sf": rights.current_gfa_sf,
            "available_gfa_sf": rights.available_gfa_sf,
            "gfa_utilization_pct": rights.gfa_utilization_pct,
            "available_footprint_sf": rights.available_footprint_sf,
            "available_dwelling_units": rights.available_dwelling_units,
            "is_vacant": rights.is_vacant,
            "is_underdeveloped": rights.is_underdeveloped,
            "is_overdeveloped": rights.is_overdeveloped,
            "rights_analyzable": rights.is_analyzable,
        })

    results_df = pd.DataFrame(records)
    result_gdf = pd.concat(
        [gdf.reset_index(drop=True), results_df], axis=1
    )
    return gpd.GeoDataFrame(result_gdf, geometry="geometry", crs=gdf.crs)


def _empty_rights_record() -> dict:
    """Return an empty record for parcels that can't be analyzed."""
    return {
        "max_gfa_sf": None,
        "current_gfa_sf": None,
        "available_gfa_sf": None,
        "gfa_utilization_pct": None,
        "available_footprint_sf": None,
        "available_dwelling_units": None,
        "is_vacant": None,
        "is_underdeveloped": None,
        "is_overdeveloped": None,
        "tdr_potential": None,
        "rights_analyzable": False,
    }
