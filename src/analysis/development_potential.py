"""
Development Potential Analyzer

Main analysis function that determines maximum by-right residential
development potential for a parcel based on zoning regulations.

This module integrates:
- Lot geometry calculations (area, width, depth)
- Zoning rules lookup
- Conformance validation
- Development limits calculation
"""

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon

from ..geometry.lot_metrics import LotMetricsCalculator
from ..rules.engine import ZoningRulesEngine
from ..rules.validators import ZoningValidator

logger = logging.getLogger(__name__)


@dataclass
class DevelopmentPotentialResult:
    """
    Complete development potential analysis result for a parcel.
    
    Contains all inputs, calculated metrics, zoning standards,
    and development limits for by-right one-family dwelling use.
    """
    
    # Parcel identification
    parcel_id: Optional[str] = None
    """Parcel identifier from source data"""
    
    # Zoning information
    zoning_district: Optional[str] = None
    """Zoning district code"""
    
    is_residential_zoning: bool = False
    """Whether parcel is in a residential zoning district"""
    
    is_split_zoned: bool = False
    """Whether parcel spans multiple zoning districts"""
    
    # Lot metrics
    lot_area_sf: Optional[float] = None
    """Lot area in square feet"""

    lot_width_ft: Optional[float] = None
    """Lot width in feet"""

    lot_depth_ft: Optional[float] = None
    """Lot depth in feet"""

    # Data source annotations for lot metrics
    lot_area_source: str = "geometry"
    """Source of lot area: 'assessor' or 'geometry'"""

    lot_width_source: str = "geometry"
    """Source of lot width: 'derived' (area/depth) or 'geometry' (MBR)"""

    lot_depth_source: str = "geometry"
    """Source of lot depth: always 'geometry' (MBR long dimension)"""
    
    # Conformance
    is_conforming: bool = False
    """Whether lot meets minimum requirements for by-right development"""
    
    conformance_status: str = "unknown"
    """Conformance status: 'conforming', 'nonconforming', or 'unknown'"""
    
    limiting_factors: list[str] = field(default_factory=list)
    """Factors limiting development (e.g., ['lot_width', 'lot_area'])"""
    
    conformance_issues: list[str] = field(default_factory=list)
    """Human-readable descriptions of conformance issues"""
    
    # Development limits
    max_height_ft: Optional[int] = None
    """Maximum building height in feet"""
    
    max_lot_coverage_pct: Optional[float] = None
    """Maximum lot coverage percentage"""
    
    max_lot_coverage_sf: Optional[float] = None
    """Maximum lot coverage in square feet"""
    
    max_building_footprint_pct: Optional[float] = None
    """Maximum main building footprint percentage"""
    
    max_building_footprint_sf: Optional[float] = None
    """Maximum main building footprint in square feet"""
    
    max_dwelling_units: int = 0
    """Maximum dwelling units allowed by-right"""
    
    required_parking_spaces: int = 0
    """Required parking spaces"""
    
    # Metadata
    notes: list[str] = field(default_factory=list)
    """Additional notes and warnings"""
    
    analysis_errors: list[str] = field(default_factory=list)
    """Any errors encountered during analysis"""
    
    def to_dict(self) -> dict:
        """Convert result to dictionary."""
        return asdict(self)
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "Development Potential Analysis",
            f"{'='*40}",
            f"Parcel ID: {self.parcel_id or 'N/A'}",
            f"Zoning District: {self.zoning_district or 'N/A'}",
            "",
            "Lot Metrics:",
            f"  Area: {self.lot_area_sf:,.0f} sf" if self.lot_area_sf else "  Area: N/A",
            f"  Width: {self.lot_width_ft:.1f} ft" if self.lot_width_ft else "  Width: N/A",
            f"  Depth: {self.lot_depth_ft:.1f} ft" if self.lot_depth_ft else "  Depth: N/A",
            "",
            f"Conformance: {self.conformance_status}",
        ]
        
        if self.limiting_factors:
            lines.append(f"  Limiting Factors: {', '.join(self.limiting_factors)}")
        
        if self.is_conforming:
            lines.extend([
                "",
                "Development Limits (By-Right):",
                f"  Max Height: {self.max_height_ft} ft",
                f"  Max Lot Coverage: {self.max_lot_coverage_sf:,.0f} sf ({self.max_lot_coverage_pct}%)" if self.max_lot_coverage_sf else "",
                f"  Max Building Footprint: {self.max_building_footprint_sf:,.0f} sf" if self.max_building_footprint_sf else "",
                f"  Max Dwelling Units: {self.max_dwelling_units}",
                f"  Required Parking: {self.required_parking_spaces} spaces",
            ])
        
        if self.notes:
            lines.extend(["", "Notes:"])
            for note in self.notes:
                lines.append(f"  - {note}")
        
        if self.analysis_errors:
            lines.extend(["", "Errors:"])
            for error in self.analysis_errors:
                lines.append(f"  - {error}")
        
        return "\n".join(lines)


class DevelopmentPotentialAnalyzer:
    """
    Analyzes maximum by-right development potential for residential parcels.
    
    Combines geometry analysis, zoning rules lookup, and conformance
    validation to determine what can be built on a parcel by-right.
    """
    
    def __init__(
        self,
        config_dir: str | Path = "config",
        crs_units: str = "feet"
    ):
        """
        Initialize the analyzer.
        
        Args:
            config_dir: Directory containing zoning rules configuration
            crs_units: Linear units of coordinate system ('feet' or 'meters')
        """
        self.config_dir = Path(config_dir)
        self.crs_units = crs_units
        
        # Initialize components
        self.rules_engine = ZoningRulesEngine(config_dir)
        self.validator = ZoningValidator(self.rules_engine)
        self.geometry_calculator = LotMetricsCalculator(crs_units=crs_units)
    
    def analyze(
        self,
        geometry: Polygon | MultiPolygon,
        zoning_district: str,
        parcel_id: Optional[str] = None,
        is_split_zoned: bool = False,
        glup_designation: Optional[str] = None,
        lot_size_override: Optional[float] = None,
    ) -> DevelopmentPotentialResult:
        """
        Analyze development potential for a single parcel.

        Args:
            geometry: Parcel geometry (Shapely Polygon or MultiPolygon)
            zoning_district: Zoning district code
            parcel_id: Optional parcel identifier
            is_split_zoned: Whether parcel spans multiple zoning districts
            glup_designation: Optional GLUP designation
            lot_size_override: Optional authoritative lot area in sq ft
                (e.g. assessor's lotSizeQty).  When provided, used instead
                of the geometry-derived area.

        Returns:
            DevelopmentPotentialResult with complete analysis
        """
        result = DevelopmentPotentialResult(
            parcel_id=parcel_id,
            zoning_district=zoning_district,
            is_split_zoned=is_split_zoned
        )
        
        # Check if district is residential
        if not self.rules_engine.is_supported_district(zoning_district):
            result.is_residential_zoning = False
            result.notes.append(
                f"District '{zoning_district}' is not a supported residential district. "
                f"Supported districts: {', '.join(self.rules_engine.get_district_codes())}"
            )
            return result
        
        result.is_residential_zoning = True
        
        # Handle split zoning
        if is_split_zoned:
            result.notes.append(
                "Parcel has split zoning - analysis uses primary zone only. "
                "Manual review recommended."
            )
        
        # Calculate lot metrics from geometry, with optional assessor override
        try:
            metrics = self.geometry_calculator.calculate(
                geometry,
                authoritative_area_sf=lot_size_override,
            )
            result.lot_area_sf = metrics.area_sf
            result.lot_width_ft = metrics.width_ft
            result.lot_depth_ft = metrics.depth_ft
            result.lot_area_source = metrics.area_source
            result.lot_width_source = metrics.width_source
            result.lot_depth_source = metrics.depth_source

            if metrics.is_irregular:
                result.notes.append(
                    f"Lot shape is irregular (shape efficiency: {metrics.shape_efficiency:.1%}). "
                    "Actual buildable area may differ from calculated metrics."
                )
        except Exception as e:
            result.analysis_errors.append(f"Geometry calculation error: {str(e)}")
            return result
        
        # Validate against zoning requirements
        try:
            validation = self.validator.validate(
                district_code=zoning_district,
                lot_area_sf=result.lot_area_sf,
                lot_width_ft=result.lot_width_ft,
                lot_depth_ft=result.lot_depth_ft
            )
            
            result.is_conforming = validation.is_conforming
            result.conformance_status = validation.status.value
            result.limiting_factors = validation.limiting_factors
            result.conformance_issues = [issue.description for issue in validation.issues]
            result.max_dwelling_units = validation.max_dwelling_units
            result.notes.extend(validation.notes)
            
        except Exception as e:
            result.analysis_errors.append(f"Validation error: {str(e)}")
            return result
        
        # Get development standards
        standards = self.rules_engine.get_standards(zoning_district)
        if standards:
            result.max_height_ft = standards.max_height_ft
            result.max_lot_coverage_pct = standards.max_lot_coverage_pct
            result.max_building_footprint_pct = standards.max_building_footprint_pct
            
            # Calculate actual limits based on lot size
            result.max_lot_coverage_sf = self.rules_engine.calculate_max_lot_coverage(
                zoning_district, result.lot_area_sf
            )
            result.max_building_footprint_sf = self.rules_engine.calculate_max_building_footprint(
                zoning_district, result.lot_area_sf
            )
            
            # Parking requirement
            result.required_parking_spaces = int(
                result.max_dwelling_units * standards.parking_spaces_per_unit
            )
        
        return result


def analyze_development_potential(
    geometry: Polygon | MultiPolygon,
    zoning_district: str,
    parcel_id: Optional[str] = None,
    config_dir: str | Path = "config",
    lot_size_override: Optional[float] = None,
    **kwargs
) -> DevelopmentPotentialResult:
    """
    Analyze development potential for a parcel.

    This is the main entry point for single-parcel analysis.

    Args:
        geometry: Parcel geometry (Shapely Polygon or MultiPolygon)
        zoning_district: Zoning district code (e.g., 'R-6')
        parcel_id: Optional parcel identifier
        config_dir: Directory containing zoning rules configuration
        lot_size_override: Optional authoritative lot area in sq ft
        **kwargs: Additional arguments passed to analyzer

    Returns:
        DevelopmentPotentialResult with complete analysis

    Example:
        >>> from shapely.geometry import box
        >>> parcel = box(0, 0, 60, 100)  # 6000 sf lot, 60ft x 100ft
        >>> result = analyze_development_potential(parcel, 'R-6')
        >>> print(result.is_conforming)
        True
        >>> print(result.max_building_footprint_sf)
        1800.0
    """
    analyzer = DevelopmentPotentialAnalyzer(config_dir=config_dir)
    return analyzer.analyze(
        geometry=geometry,
        zoning_district=zoning_district,
        parcel_id=parcel_id,
        lot_size_override=lot_size_override,
        **kwargs
    )


def analyze_parcel_by_id(
    parcel_id: str,
    parcels_gdf: gpd.GeoDataFrame,
    parcel_id_column: str = "RPC",
    zoning_column: str = "zoning_district",
    config_dir: str | Path = "config"
) -> DevelopmentPotentialResult:
    """
    Analyze development potential for a parcel by its ID.
    
    Convenience function for analyzing parcels from an enriched GeoDataFrame.
    
    Args:
        parcel_id: Parcel identifier to look up
        parcels_gdf: GeoDataFrame with parcel data (must include zoning)
        parcel_id_column: Name of column containing parcel IDs
        zoning_column: Name of column containing zoning district codes
        config_dir: Directory containing zoning rules configuration
        
    Returns:
        DevelopmentPotentialResult with complete analysis
        
    Raises:
        ValueError: If parcel ID not found
    """
    # Find parcel
    mask = parcels_gdf[parcel_id_column] == parcel_id
    if not mask.any():
        raise ValueError(f"Parcel '{parcel_id}' not found in dataset")
    
    parcel = parcels_gdf.loc[mask].iloc[0]
    
    # Extract data
    geometry = parcel.geometry
    zoning = parcel.get(zoning_column)
    is_split = parcel.get('is_split_zoned', False)
    glup = parcel.get('glup_designation')
    
    if zoning is None:
        result = DevelopmentPotentialResult(parcel_id=parcel_id)
        result.analysis_errors.append("No zoning district found for parcel")
        return result
    
    # Analyze
    return analyze_development_potential(
        geometry=geometry,
        zoning_district=zoning,
        parcel_id=parcel_id,
        is_split_zoned=is_split,
        glup_designation=glup,
        config_dir=config_dir
    )


def analyze_geodataframe(
    gdf: gpd.GeoDataFrame,
    zoning_column: str = "zoning_district",
    parcel_id_column: Optional[str] = None,
    config_dir: str | Path = "config"
) -> gpd.GeoDataFrame:
    """
    Analyze development potential for all parcels in a GeoDataFrame.
    
    Adds analysis results as new columns to the GeoDataFrame.
    
    Args:
        gdf: GeoDataFrame with parcel geometries and zoning
        zoning_column: Name of column containing zoning district codes
        parcel_id_column: Optional column with parcel IDs
        config_dir: Directory containing zoning rules configuration
        
    Returns:
        GeoDataFrame with added analysis columns
    """
    analyzer = DevelopmentPotentialAnalyzer(config_dir=config_dir)
    
    results = []
    for idx, row in gdf.iterrows():
        parcel_id = row.get(parcel_id_column) if parcel_id_column else str(idx)
        zoning = row.get(zoning_column)
        is_split = row.get('is_split_zoned', False)
        
        if zoning is None:
            results.append({
                'is_conforming': None,
                'max_height_ft': None,
                'max_building_footprint_sf': None,
                'max_lot_coverage_sf': None,
                'max_dwelling_units': None,
                'analysis_status': 'no_zoning'
            })
            continue
        
        try:
            result = analyzer.analyze(
                geometry=row.geometry,
                zoning_district=zoning,
                parcel_id=parcel_id,
                is_split_zoned=is_split
            )
            
            results.append({
                'is_conforming': result.is_conforming,
                'conformance_status': result.conformance_status,
                'lot_area_calc_sf': result.lot_area_sf,
                'lot_width_calc_ft': result.lot_width_ft,
                'max_height_ft': result.max_height_ft,
                'max_building_footprint_sf': result.max_building_footprint_sf,
                'max_lot_coverage_sf': result.max_lot_coverage_sf,
                'max_dwelling_units': result.max_dwelling_units,
                'limiting_factors': ','.join(result.limiting_factors) if result.limiting_factors else None,
                'analysis_status': 'success' if not result.analysis_errors else 'error'
            })
        except Exception as e:
            logger.warning(f"Error analyzing parcel {parcel_id}: {e}")
            results.append({
                'is_conforming': None,
                'analysis_status': 'error'
            })
    
    # Add results to GeoDataFrame
    import pandas as pd
    results_df = pd.DataFrame(results)

    # Concatenate
    result_gdf = pd.concat([gdf.reset_index(drop=True), results_df], axis=1)
    
    return gpd.GeoDataFrame(result_gdf, geometry='geometry', crs=gdf.crs)
