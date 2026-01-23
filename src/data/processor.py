"""
Data Processor for Arlington Zoning Analyzer

Handles spatial joins between parcel data and zoning polygons,
enriches parcel data with zoning attributes, and prepares data
for development potential analysis.
"""

import logging
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    Processes and enriches Arlington County GIS data.
    
    Performs spatial joins between parcels and zoning districts,
    identifies split-zoned parcels, and prepares data for analysis.
    """
    
    # Expected CRS for Arlington County data (Virginia State Plane North)
    ARLINGTON_CRS = "EPSG:2283"  # NAD83 / Virginia North (ftUS)
    WGS84_CRS = "EPSG:4326"
    
    # Residential zoning district prefixes
    RESIDENTIAL_PREFIXES = ("R-", "R2-", "R1")
    
    def __init__(
        self,
        parcels_gdf: gpd.GeoDataFrame,
        zoning_gdf: gpd.GeoDataFrame,
        glup_gdf: Optional[gpd.GeoDataFrame] = None
    ):
        """
        Initialize the processor with loaded GeoDataFrames.
        
        Args:
            parcels_gdf: GeoDataFrame of parcel polygons
            zoning_gdf: GeoDataFrame of zoning district polygons
            glup_gdf: Optional GeoDataFrame of GLUP designations
        """
        self.parcels = parcels_gdf.copy()
        self.zoning = zoning_gdf.copy()
        self.glup = glup_gdf.copy() if glup_gdf is not None else None
        
        self._ensure_consistent_crs()
        
    def _ensure_consistent_crs(self) -> None:
        """Ensure all datasets use the same CRS for accurate spatial operations."""
        target_crs = self.ARLINGTON_CRS
        
        if self.parcels.crs is None:
            logger.warning("Parcels GeoDataFrame has no CRS, assuming WGS84")
            self.parcels = self.parcels.set_crs(self.WGS84_CRS)
        
        if self.zoning.crs is None:
            logger.warning("Zoning GeoDataFrame has no CRS, assuming WGS84")
            self.zoning = self.zoning.set_crs(self.WGS84_CRS)
        
        # Reproject to Virginia State Plane for accurate area calculations
        if self.parcels.crs != target_crs:
            logger.info(f"Reprojecting parcels from {self.parcels.crs} to {target_crs}")
            self.parcels = self.parcels.to_crs(target_crs)
        
        if self.zoning.crs != target_crs:
            logger.info(f"Reprojecting zoning from {self.zoning.crs} to {target_crs}")
            self.zoning = self.zoning.to_crs(target_crs)
        
        if self.glup is not None:
            if self.glup.crs is None:
                self.glup = self.glup.set_crs(self.WGS84_CRS)
            if self.glup.crs != target_crs:
                logger.info(f"Reprojecting GLUP from {self.glup.crs} to {target_crs}")
                self.glup = self.glup.to_crs(target_crs)
    
    def identify_zoning_column(self) -> str:
        """
        Identify the column containing zoning district codes.
        
        Returns:
            Name of the zoning code column
            
        Raises:
            ValueError: If no zoning column can be identified
        """
        # Common column names for zoning codes
        candidates = ['ZONING', 'ZONE', 'ZONE_CODE', 'ZONING_CODE', 'ZONECODE',
                      'zoning', 'zone', 'zone_code', 'zoning_code', 'ZoneCode',
                      'ZONINGCODE', 'DISTRICT', 'district']
        
        for col in candidates:
            if col in self.zoning.columns:
                logger.info(f"Identified zoning column: {col}")
                return col
        
        # Try to find column with R-XX pattern values
        for col in self.zoning.columns:
            if self.zoning[col].dtype == 'object':
                sample = self.zoning[col].dropna().head(100)
                if sample.str.contains(r'^R-?\d', regex=True, na=False).any():
                    logger.info(f"Identified zoning column by pattern: {col}")
                    return col
        
        raise ValueError(
            f"Could not identify zoning column. Available columns: {list(self.zoning.columns)}"
        )
    
    def identify_parcel_id_column(self) -> str:
        """
        Identify the column containing parcel IDs.
        
        Returns:
            Name of the parcel ID column
        """
        # Common column names for parcel IDs
        candidates = ['RPC', 'PARCEL_ID', 'PARCELID', 'APN', 'PIN', 
                      'parcel_id', 'rpc', 'OBJECTID', 'FID',
                      'ParcelID', 'Parcel_ID']
        
        for col in candidates:
            if col in self.parcels.columns:
                logger.info(f"Identified parcel ID column: {col}")
                return col
        
        # Default to first non-geometry column
        non_geom_cols = [c for c in self.parcels.columns if c != 'geometry']
        if non_geom_cols:
            logger.warning(f"Using first column as parcel ID: {non_geom_cols[0]}")
            return non_geom_cols[0]
        
        raise ValueError("Could not identify parcel ID column")
    
    def join_parcels_to_zoning(self) -> gpd.GeoDataFrame:
        """
        Perform spatial join between parcels and zoning districts.
        
        Uses the centroid of each parcel to determine its zoning district.
        Parcels that span multiple zones are flagged for review.
        
        Returns:
            GeoDataFrame with parcels enriched with zoning information
        """
        logger.info("Performing spatial join: parcels to zoning...")
        
        zoning_col = self.identify_zoning_column()
        parcel_id_col = self.identify_parcel_id_column()
        
        # Create centroid points for joining
        parcels_with_centroid = self.parcels.copy()
        parcels_with_centroid['_centroid'] = parcels_with_centroid.geometry.centroid
        
        # Also check for split zoning using intersection
        # A parcel has split zoning if it intersects multiple zoning districts
        logger.info("Checking for split-zoned parcels...")
        
        # Spatial join using centroids (determines primary zoning)
        centroid_gdf = parcels_with_centroid.set_geometry('_centroid')
        joined = gpd.sjoin(
            centroid_gdf,
            self.zoning[[zoning_col, 'geometry']],
            how='left',
            predicate='within'
        )
        
        # Restore original geometry
        joined = joined.set_geometry(parcels_with_centroid.geometry)
        joined = joined.drop(columns=['_centroid'], errors='ignore')
        
        # Rename zoning column for clarity
        joined = joined.rename(columns={zoning_col: 'zoning_district'})
        
        # Remove duplicate index column from sjoin
        joined = joined.drop(columns=['index_right'], errors='ignore')
        
        # Identify split-zoned parcels (intersect multiple zoning districts)
        split_zoning = self._identify_split_zoning(parcel_id_col)
        joined['is_split_zoned'] = joined[parcel_id_col].isin(split_zoning)
        
        # Add residential flag
        joined['is_residential_zoning'] = joined['zoning_district'].apply(
            lambda x: self._is_residential_district(x) if pd.notna(x) else False
        )
        
        logger.info(f"Joined {len(joined)} parcels to zoning districts")
        logger.info(f"  - Residential parcels: {joined['is_residential_zoning'].sum()}")
        logger.info(f"  - Split-zoned parcels: {joined['is_split_zoned'].sum()}")
        logger.info(f"  - Parcels with no zoning match: {joined['zoning_district'].isna().sum()}")
        
        return joined
    
    def _identify_split_zoning(self, parcel_id_col: str) -> set:
        """
        Identify parcels that span multiple zoning districts.
        
        Returns:
            Set of parcel IDs that have split zoning
        """
        zoning_col = self.identify_zoning_column()
        
        # Spatial join using actual polygon intersection
        intersections = gpd.sjoin(
            self.parcels[[parcel_id_col, 'geometry']],
            self.zoning[[zoning_col, 'geometry']],
            how='left',
            predicate='intersects'
        )
        
        # Find parcels that intersect multiple zones
        zone_counts = intersections.groupby(parcel_id_col)[zoning_col].nunique()
        split_parcels = set(zone_counts[zone_counts > 1].index)
        
        return split_parcels
    
    def _is_residential_district(self, zoning_code: str) -> bool:
        """Check if a zoning code is a residential district."""
        if not isinstance(zoning_code, str):
            return False
        
        code_upper = zoning_code.upper().strip()
        
        # Check for R districts from Article 5
        residential_districts = {
            'R-20', 'R-10', 'R-10T', 'R-8', 'R-6', 'R-5', 
            'R15-30T', 'R2-7',
            # Also include variants without hyphens
            'R20', 'R10', 'R10T', 'R8', 'R6', 'R5', 'R1530T', 'R27'
        }
        
        return code_upper in residential_districts or any(
            code_upper.startswith(prefix) for prefix in self.RESIDENTIAL_PREFIXES
        )
    
    def process_all(self, output_path: Optional[Path] = None) -> gpd.GeoDataFrame:
        """
        Run full processing pipeline and optionally save results.
        
        Args:
            output_path: Optional path to save processed data (GeoPackage format)
            
        Returns:
            Fully processed and enriched GeoDataFrame
        """
        # Join parcels to zoning
        enriched = self.join_parcels_to_zoning()
        
        # Optionally join to GLUP
        if self.glup is not None:
            enriched = self._join_to_glup(enriched)
        
        # Save if path provided
        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            enriched.to_file(output_path, driver='GPKG')
            logger.info(f"Saved processed data to {output_path}")
        
        return enriched
    
    def _join_to_glup(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Join GLUP designation to parcels using centroid."""
        logger.info("Joining GLUP designations...")
        
        # Identify GLUP designation column
        glup_cols = ['GLUP', 'LANDUSE', 'LAND_USE', 'DESIGNATION', 
                     'glup', 'landuse', 'land_use']
        glup_col = None
        for col in glup_cols:
            if col in self.glup.columns:
                glup_col = col
                break
        
        if glup_col is None:
            logger.warning("Could not identify GLUP designation column, skipping GLUP join")
            return gdf
        
        # Create centroids for joining
        gdf_with_centroid = gdf.copy()
        gdf_with_centroid['_centroid'] = gdf_with_centroid.geometry.centroid
        centroid_gdf = gdf_with_centroid.set_geometry('_centroid')
        
        # Join
        joined = gpd.sjoin(
            centroid_gdf,
            self.glup[[glup_col, 'geometry']],
            how='left',
            predicate='within'
        )
        
        # Restore geometry and clean up
        joined = joined.set_geometry(gdf_with_centroid.geometry)
        joined = joined.drop(columns=['_centroid', 'index_right'], errors='ignore')
        joined = joined.rename(columns={glup_col: 'glup_designation'})
        
        return joined


def process_arlington_data(
    raw_data_dir: str | Path = "data/raw",
    output_path: str | Path = "data/processed/parcels_enriched.gpkg"
) -> gpd.GeoDataFrame:
    """
    Convenience function to process downloaded Arlington County data.
    
    Args:
        raw_data_dir: Directory containing downloaded GeoJSON files
        output_path: Path for output GeoPackage file
        
    Returns:
        Processed GeoDataFrame with parcels enriched with zoning
    """
    raw_data_dir = Path(raw_data_dir)
    
    # Load datasets
    logger.info("Loading datasets...")
    parcels = gpd.read_file(raw_data_dir / "parcels.geojson")
    zoning = gpd.read_file(raw_data_dir / "zoning.geojson")
    
    # Try to load GLUP if available
    glup_path = raw_data_dir / "glup.geojson"
    glup = gpd.read_file(glup_path) if glup_path.exists() else None
    
    # Process
    processor = DataProcessor(parcels, zoning, glup)
    return processor.process_all(output_path=output_path)
