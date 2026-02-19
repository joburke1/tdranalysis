"""
Data Processor for Arlington Zoning Analyzer

Handles spatial joins between parcel data and zoning polygons,
tabular joins to property/assessment records, and prepares
enriched parcel data for development potential analysis.
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
    tabular joins to property/assessment records, identifies
    split-zoned parcels, and prepares data for analysis.
    """

    # Expected CRS for Arlington County data (Virginia State Plane North)
    ARLINGTON_CRS = "EPSG:2283"  # NAD83 / Virginia North (ftUS)
    WGS84_CRS = "EPSG:4326"

    # Residential zoning district prefixes
    RESIDENTIAL_PREFIXES = ("R-", "R2-", "R1")

    # Columns to keep from the property dataset when joining
    PROPERTY_COLUMNS = [
        "realEstatePropertyCode",
        "grossFloorAreaSquareFeetQty",
        "storyHeightCnt",
        "propertyYearBuilt",
        "numberOfUnitsCnt",
        "lotSizeQty",
        "propertyClassTypeCode",
        "propertyClassTypeDsc",
        "zoningDescListText",
        "commercialInd",
        "mixedUseInd",
    ]

    # Columns to keep from the assessment dataset when joining
    ASSESSMENT_COLUMNS = [
        "realEstatePropertyCode",
        "improvementValueAmt",
        "landValueAmt",
        "totalValueAmt",
    ]

    def __init__(
        self,
        parcels_gdf: gpd.GeoDataFrame,
        zoning_gdf: gpd.GeoDataFrame,
        glup_gdf: Optional[gpd.GeoDataFrame] = None,
        property_df: Optional[pd.DataFrame] = None,
        assessment_df: Optional[pd.DataFrame] = None,
        civic_associations_gdf: Optional[gpd.GeoDataFrame] = None,
    ):
        """
        Initialize the processor with loaded data.

        Args:
            parcels_gdf: GeoDataFrame of parcel polygons
            zoning_gdf: GeoDataFrame of zoning district polygons
            glup_gdf: Optional GeoDataFrame of GLUP designations
            property_df: Optional DataFrame of property attributes from the Arlington Open Data API
            assessment_df: Optional DataFrame of assessment values from the Arlington Open Data API
            civic_associations_gdf: Optional GeoDataFrame of civic association (neighborhood) polygons
        """
        self.parcels = parcels_gdf.copy()
        self.zoning = zoning_gdf.copy()
        self.glup = glup_gdf.copy() if glup_gdf is not None else None
        self.property_data = property_df.copy() if property_df is not None else None
        self.assessment_data = assessment_df.copy() if assessment_df is not None else None
        self.civic_associations = (
            civic_associations_gdf.copy() if civic_associations_gdf is not None else None
        )

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

        if self.civic_associations is not None:
            if self.civic_associations.crs is None:
                self.civic_associations = self.civic_associations.set_crs(self.WGS84_CRS)
            if self.civic_associations.crs != target_crs:
                logger.info(
                    f"Reprojecting civic associations from "
                    f"{self.civic_associations.crs} to {target_crs}"
                )
                self.civic_associations = self.civic_associations.to_crs(target_crs)
    
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
                      'ZONINGCODE', 'DISTRICT', 'district',
                      # Arlington-specific column names
                      'ZN_DESIG', 'zn_desig', 'REA_ZONECODE', 'rea_zonecode']
        
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
                      'parcel_id', 'rpc', 'FID',
                      'ParcelID', 'Parcel_ID',
                      # Arlington-specific: Real Property Code master field
                      'RPCMSTR', 'rpcmstr']
        
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
    
    def join_property_data(
        self, gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """
        Join property attributes to parcels via Real Property Code (RPC).

        Adds building characteristics from the Arlington Open Data API
        property dataset: gross floor area, story count, year built,
        number of units, and property classification.

        Args:
            gdf: GeoDataFrame with a parcel ID column matching RPC format

        Returns:
            GeoDataFrame enriched with property attributes
        """
        if self.property_data is None:
            logger.info("No property data provided, skipping property join")
            return gdf

        parcel_id_col = self.identify_parcel_id_column()
        logger.info(
            f"Joining property data to parcels via "
            f"'{parcel_id_col}' → 'realEstatePropertyCode'..."
        )

        # Select and deduplicate property columns
        available_cols = [
            c for c in self.PROPERTY_COLUMNS if c in self.property_data.columns
        ]
        prop_subset = self.property_data[available_cols].copy()

        # Keep only the most recent record per RPC (last in dataset)
        prop_subset = prop_subset.drop_duplicates(
            subset=["realEstatePropertyCode"], keep="last"
        )

        before_count = len(gdf)
        enriched = gdf.merge(
            prop_subset,
            left_on=parcel_id_col,
            right_on="realEstatePropertyCode",
            how="left",
        )
        # Drop the redundant join key if it's different from parcel_id_col
        if parcel_id_col != "realEstatePropertyCode":
            enriched = enriched.drop(columns=["realEstatePropertyCode"], errors="ignore")

        matched = enriched["grossFloorAreaSquareFeetQty"].notna().sum()
        logger.info(
            f"Property join: {matched}/{before_count} parcels matched "
            f"({matched / before_count * 100:.1f}%)"
        )

        return enriched

    def join_assessment_data(
        self, gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """
        Join assessment values to parcels via Real Property Code (RPC).

        Adds land value, improvement value, and total assessed value
        from the Arlington Open Data API assessment dataset.

        Args:
            gdf: GeoDataFrame with a parcel ID column matching RPC format

        Returns:
            GeoDataFrame enriched with assessment values
        """
        if self.assessment_data is None:
            logger.info("No assessment data provided, skipping assessment join")
            return gdf

        parcel_id_col = self.identify_parcel_id_column()
        logger.info(
            f"Joining assessment data to parcels via "
            f"'{parcel_id_col}' → 'realEstatePropertyCode'..."
        )

        available_cols = [
            c for c in self.ASSESSMENT_COLUMNS if c in self.assessment_data.columns
        ]
        assess_subset = self.assessment_data[available_cols].copy()

        # Keep only the most recent assessment per RPC
        assess_subset = assess_subset.drop_duplicates(
            subset=["realEstatePropertyCode"], keep="last"
        )

        before_count = len(gdf)
        enriched = gdf.merge(
            assess_subset,
            left_on=parcel_id_col,
            right_on="realEstatePropertyCode",
            how="left",
        )
        if parcel_id_col != "realEstatePropertyCode":
            enriched = enriched.drop(columns=["realEstatePropertyCode"], errors="ignore")

        matched = enriched["totalValueAmt"].notna().sum()
        logger.info(
            f"Assessment join: {matched}/{before_count} parcels matched "
            f"({matched / before_count * 100:.1f}%)"
        )

        return enriched

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

        # Optionally join civic association (neighborhood) boundaries
        if self.civic_associations is not None:
            enriched = self.join_civic_associations(enriched)

        # Join property attributes (building characteristics)
        enriched = self.join_property_data(enriched)

        # Join assessment values
        enriched = self.join_assessment_data(enriched)

        # Save if path provided
        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            enriched.to_file(output_path, driver='GPKG')
            logger.info(f"Saved processed data to {output_path}")

        return enriched
    
    def join_civic_associations(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Join civic association (neighborhood) name to parcels using centroid.

        Adds a 'civic_association' column to the GeoDataFrame. Parcels that
        do not fall within any civic association boundary get NaN.

        Args:
            gdf: GeoDataFrame of parcels (must share CRS with civic_associations)

        Returns:
            GeoDataFrame with added 'civic_association' column
        """
        if self.civic_associations is None:
            logger.info("No civic associations data provided, skipping neighborhood join")
            return gdf

        logger.info("Joining civic association boundaries to parcels...")

        # Find the name column — try common patterns
        name_candidates = [
            "CIVIC_ASSOC", "CIVIC_ASSOCIATION", "NAME", "ASSOC_NAME",
            "civic_assoc", "civic_association", "name", "assoc_name",
            "ASSOCIATION", "association",
            # Arlington-specific column name
            "CIVIC", "civic", "LABEL", "label",
        ]
        name_col = None
        for col in name_candidates:
            if col in self.civic_associations.columns:
                name_col = col
                break

        if name_col is None:
            # Use first non-geometry string column
            for col in self.civic_associations.columns:
                if col != "geometry" and self.civic_associations[col].dtype == "object":
                    name_col = col
                    logger.warning(
                        f"Could not identify civic association name column; "
                        f"using '{col}'"
                    )
                    break

        if name_col is None:
            logger.warning("Cannot identify civic association name column; skipping join")
            return gdf

        # Centroid join
        gdf_copy = gdf.copy()
        gdf_copy["_centroid"] = gdf_copy.geometry.centroid
        centroid_gdf = gdf_copy.set_geometry("_centroid")

        joined = gpd.sjoin(
            centroid_gdf,
            self.civic_associations[[name_col, "geometry"]],
            how="left",
            predicate="within",
        )

        joined = joined.set_geometry(gdf_copy.geometry)
        joined = joined.drop(columns=["_centroid", "index_right"], errors="ignore")
        joined = joined.rename(columns={name_col: "civic_association"})

        matched = joined["civic_association"].notna().sum()
        logger.info(
            f"Civic association join: {matched}/{len(joined)} parcels matched "
            f"({matched / len(joined) * 100:.1f}%)"
        )

        return joined

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

    Loads all available datasets (GIS and API) from the raw data directory
    and runs the full processing pipeline.

    Args:
        raw_data_dir: Directory containing downloaded data files
        output_path: Path for output GeoPackage file

    Returns:
        Processed GeoDataFrame with parcels enriched with zoning,
        property attributes, and assessment values
    """
    import json as _json

    raw_data_dir = Path(raw_data_dir)

    # Load GIS datasets
    logger.info("Loading datasets...")
    parcels = gpd.read_file(raw_data_dir / "parcels.geojson")
    zoning = gpd.read_file(raw_data_dir / "zoning.geojson")

    # Try to load optional GIS datasets
    glup_path = raw_data_dir / "glup.geojson"
    glup = gpd.read_file(glup_path) if glup_path.exists() else None

    civic_assoc_path = raw_data_dir / "civic_associations.geojson"
    civic_associations = (
        gpd.read_file(civic_assoc_path) if civic_assoc_path.exists() else None
    )
    if civic_associations is not None:
        logger.info(f"Loaded {len(civic_associations)} civic association polygons")

    # Try to load API datasets
    property_df = None
    property_path = raw_data_dir / "property.json"
    if property_path.exists():
        logger.info("Loading property data...")
        with open(property_path, 'r') as f:
            property_df = pd.DataFrame(_json.load(f))

    assessment_df = None
    assessment_path = raw_data_dir / "assessment.json"
    if assessment_path.exists():
        logger.info("Loading assessment data...")
        with open(assessment_path, 'r') as f:
            assessment_df = pd.DataFrame(_json.load(f))

    # Process
    processor = DataProcessor(
        parcels, zoning, glup,
        property_df=property_df,
        assessment_df=assessment_df,
        civic_associations_gdf=civic_associations,
    )
    return processor.process_all(output_path=output_path)
