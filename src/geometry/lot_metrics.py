"""
Lot Metrics Calculator

Calculates geometric properties of parcels needed for zoning analysis:
- Lot area (in square feet)
- Lot width (minimum average width)
- Lot depth
- Frontage

Uses minimum bounding rectangle as the primary method for width/depth
calculations, with the architecture supporting future enhancements.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.affinity import rotate
from shapely import minimum_rotated_rectangle

logger = logging.getLogger(__name__)


@dataclass
class LotMetrics:
    """Container for calculated lot metrics."""

    area_sf: float
    """Lot area in square feet"""

    width_ft: float
    """Lot width in feet (shorter dimension of bounding rectangle)"""

    depth_ft: float
    """Lot depth in feet (longer dimension of bounding rectangle)"""

    perimeter_ft: float
    """Lot perimeter in feet"""

    frontage_ft: Optional[float] = None
    """Street frontage in feet (if calculable)"""

    is_irregular: bool = False
    """Flag indicating if lot shape is highly irregular"""

    bounding_rect_area_sf: Optional[float] = None
    """Area of minimum bounding rectangle (for shape analysis)"""

    shape_efficiency: Optional[float] = None
    """Ratio of lot area to bounding rectangle area (1.0 = perfect rectangle)"""

    area_source: str = "geometry"
    """Source of area_sf: 'assessor' (from lotSizeQty) or 'geometry' (from polygon)"""

    width_source: str = "geometry"
    """Source of width_ft: 'derived' (area/depth) or 'geometry' (from MBR)"""

    depth_source: str = "geometry"
    """Source of depth_ft: always 'geometry' (from MBR long dimension)"""


class LotMetricsCalculator:
    """
    Calculates lot metrics from parcel geometry.
    
    The calculator assumes input geometries are in a projected coordinate
    system with linear units of feet (Virginia State Plane North - EPSG:2283).
    
    For lot width calculation, uses the minimum rotated bounding rectangle
    method: the shorter dimension of the bounding rectangle is treated as
    the width, and the longer as the depth.
    """
    
    # Threshold for flagging irregular lots
    # If actual area is less than this fraction of bounding rect area, lot is irregular
    IRREGULAR_THRESHOLD = 0.6
    
    def __init__(self, crs_units: str = "feet"):
        """
        Initialize the calculator.
        
        Args:
            crs_units: Linear units of the coordinate system ('feet' or 'meters')
        """
        self.crs_units = crs_units
        
        # Conversion factor to square feet
        if crs_units == "meters":
            self.to_sf = 10.7639  # sq meters to sq feet
            self.to_ft = 3.28084  # meters to feet
        else:
            self.to_sf = 1.0
            self.to_ft = 1.0
    
    def calculate(
        self,
        geometry: Polygon | MultiPolygon,
        authoritative_area_sf: Optional[float] = None,
    ) -> LotMetrics:
        """
        Calculate all lot metrics for a parcel geometry.

        Args:
            geometry: Shapely Polygon or MultiPolygon representing the parcel
            authoritative_area_sf: Optional lot area from an authoritative source
                (e.g. assessor's lotSizeQty).  When provided, this value is used
                for area_sf instead of the polygon geometry area, and width_ft is
                derived as area / depth so all three values are consistent.

        Returns:
            LotMetrics object containing calculated values

        Raises:
            ValueError: If geometry is invalid or empty
        """
        if geometry is None or geometry.is_empty:
            raise ValueError("Cannot calculate metrics for empty geometry")

        if not geometry.is_valid:
            # Try to fix invalid geometry
            geometry = geometry.buffer(0)
            if not geometry.is_valid:
                raise ValueError("Invalid geometry that cannot be repaired")

        # Handle MultiPolygon by using the largest polygon
        if isinstance(geometry, MultiPolygon):
            geometry = max(geometry.geoms, key=lambda g: g.area)

        # Calculate basic metrics from geometry
        geom_area_sf = geometry.area * self.to_sf
        perimeter_ft = geometry.length * self.to_ft

        # Calculate width and depth using minimum rotated bounding rectangle
        geom_width_ft, depth_ft, bounding_rect = self._calculate_dimensions(geometry)

        # Decide which area to use and derive consistent width
        if authoritative_area_sf is not None and authoritative_area_sf > 0:
            area_sf = authoritative_area_sf
            area_source = "assessor"
            # Derive width from authoritative area / MBR depth for consistency
            if depth_ft > 0:
                width_ft = area_sf / depth_ft
                width_source = "derived"
            else:
                width_ft = geom_width_ft
                width_source = "geometry"
        else:
            area_sf = geom_area_sf
            area_source = "geometry"
            width_ft = geom_width_ft
            width_source = "geometry"

        # Calculate shape metrics (always based on geometry for shape analysis)
        bounding_area = bounding_rect.area * self.to_sf if bounding_rect else None
        shape_efficiency = geom_area_sf / bounding_area if bounding_area else None
        is_irregular = shape_efficiency < self.IRREGULAR_THRESHOLD if shape_efficiency else False

        return LotMetrics(
            area_sf=round(area_sf, 1),
            width_ft=round(width_ft, 1),
            depth_ft=round(depth_ft, 1),
            perimeter_ft=round(perimeter_ft, 1),
            bounding_rect_area_sf=round(bounding_area, 1) if bounding_area else None,
            shape_efficiency=round(shape_efficiency, 3) if shape_efficiency else None,
            is_irregular=is_irregular,
            area_source=area_source,
            width_source=width_source,
            depth_source="geometry",
        )
    
    def _calculate_dimensions(
        self, 
        geometry: Polygon
    ) -> tuple[float, float, Optional[Polygon]]:
        """
        Calculate width and depth using minimum rotated bounding rectangle.
        
        The shorter dimension is considered the width, longer is depth.
        This aligns with typical lot orientation where width is perpendicular
        to the street and depth runs from front to back.
        
        Args:
            geometry: Shapely Polygon
            
        Returns:
            Tuple of (width_ft, depth_ft, bounding_rectangle)
        """
        try:
            # Get minimum rotated bounding rectangle
            bounding_rect = minimum_rotated_rectangle(geometry)
            
            if bounding_rect is None or bounding_rect.is_empty:
                # Fallback to axis-aligned bounding box
                return self._fallback_dimensions(geometry)
            
            # Get the coordinates of the bounding rectangle
            coords = list(bounding_rect.exterior.coords)
            
            # Calculate edge lengths (rectangle has 4 vertices + closing vertex)
            edge1_length = self._distance(coords[0], coords[1]) * self.to_ft
            edge2_length = self._distance(coords[1], coords[2]) * self.to_ft
            
            # Width is shorter dimension, depth is longer
            width_ft = min(edge1_length, edge2_length)
            depth_ft = max(edge1_length, edge2_length)
            
            return width_ft, depth_ft, bounding_rect
            
        except Exception as e:
            logger.warning(f"Error calculating bounding rectangle: {e}")
            return self._fallback_dimensions(geometry)
    
    def _fallback_dimensions(
        self, 
        geometry: Polygon
    ) -> tuple[float, float, Optional[Polygon]]:
        """
        Fallback dimension calculation using axis-aligned bounding box.
        
        Args:
            geometry: Shapely Polygon
            
        Returns:
            Tuple of (width_ft, depth_ft, None)
        """
        minx, miny, maxx, maxy = geometry.bounds
        
        dim1 = (maxx - minx) * self.to_ft
        dim2 = (maxy - miny) * self.to_ft
        
        width_ft = min(dim1, dim2)
        depth_ft = max(dim1, dim2)
        
        return width_ft, depth_ft, None
    
    @staticmethod
    def _distance(p1: tuple, p2: tuple) -> float:
        """Calculate Euclidean distance between two points."""
        return np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
    
    def calculate_frontage(
        self, 
        parcel_geometry: Polygon,
        street_geometry: Polygon | None = None
    ) -> Optional[float]:
        """
        Calculate street frontage for a parcel.
        
        If street geometry is provided, calculates the length of the
        parcel boundary that intersects with the street right-of-way.
        
        Args:
            parcel_geometry: Shapely Polygon of the parcel
            street_geometry: Optional Shapely geometry of the street
            
        Returns:
            Frontage in feet, or None if not calculable
        """
        if street_geometry is None:
            return None
        
        try:
            # Get the intersection of parcel boundary with street
            parcel_boundary = parcel_geometry.boundary
            intersection = parcel_boundary.intersection(street_geometry)
            
            if intersection.is_empty:
                return None
            
            frontage_ft = intersection.length * self.to_ft
            return round(frontage_ft, 1)
            
        except Exception as e:
            logger.warning(f"Error calculating frontage: {e}")
            return None


def calculate_lot_metrics(
    geometry: Polygon | MultiPolygon,
    crs_units: str = "feet"
) -> LotMetrics:
    """
    Convenience function to calculate lot metrics for a single geometry.
    
    Args:
        geometry: Shapely Polygon or MultiPolygon
        crs_units: Linear units of the coordinate system
        
    Returns:
        LotMetrics object
    """
    calculator = LotMetricsCalculator(crs_units=crs_units)
    return calculator.calculate(geometry)


def add_metrics_to_geodataframe(
    gdf,
    geometry_column: str = "geometry",
    crs_units: str = "feet"
):
    """
    Add lot metrics columns to a GeoDataFrame.
    
    Args:
        gdf: GeoDataFrame with parcel geometries
        geometry_column: Name of the geometry column
        crs_units: Linear units of the coordinate system
        
    Returns:
        GeoDataFrame with added metric columns
    """
    import geopandas as gpd
    
    calculator = LotMetricsCalculator(crs_units=crs_units)
    
    metrics_data = []
    for idx, row in gdf.iterrows():
        try:
            metrics = calculator.calculate(row[geometry_column])
            metrics_data.append({
                'lot_area_sf': metrics.area_sf,
                'lot_width_ft': metrics.width_ft,
                'lot_depth_ft': metrics.depth_ft,
                'lot_perimeter_ft': metrics.perimeter_ft,
                'shape_efficiency': metrics.shape_efficiency,
                'is_irregular_lot': metrics.is_irregular
            })
        except Exception as e:
            logger.warning(f"Error calculating metrics for row {idx}: {e}")
            metrics_data.append({
                'lot_area_sf': None,
                'lot_width_ft': None,
                'lot_depth_ft': None,
                'lot_perimeter_ft': None,
                'shape_efficiency': None,
                'is_irregular_lot': None
            })
    
    metrics_df = gpd.pd.DataFrame(metrics_data)
    
    # Concatenate with original GeoDataFrame
    result = gpd.pd.concat([gdf.reset_index(drop=True), metrics_df], axis=1)
    
    return gpd.GeoDataFrame(result, geometry=geometry_column, crs=gdf.crs)
