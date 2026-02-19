"""
Arlington County Data Downloader

Downloads geospatial data from Arlington County's GIS Open Data Portal
(gisdata-arlgis.opendata.arcgis.com) and property/assessment data from
the Arlington Open Data API (datahub-v2.arlingtonva.us).

GIS data is downloaded in GeoJSON format. Property and assessment data
is downloaded as JSON from paginated REST API endpoints.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import requests
import geopandas as gpd

logger = logging.getLogger(__name__)


class ArlingtonDataDownloader:
    """
    Downloads and caches GIS data from Arlington County's Open Data Portal
    and property/assessment data from the Arlington Open Data API.

    GIS datasets are downloaded as single GeoJSON files.
    API datasets are downloaded via paginated REST endpoints and saved as JSON.
    """

    # ArcGIS Open Data Hub endpoints for Arlington County
    # These URLs provide GeoJSON downloads for each dataset
    DATASETS = {
        "parcels": {
            "name": "REA Property Polygons",
            "description": "Real estate property parcel boundaries",
            "url": "https://gisdata-arlgis.opendata.arcgis.com/api/download/v1/items/e22afb85e1414f4996c2b5264df90a07/geojson?layers=0",
            "filename": "parcels.geojson"
        },
        "zoning": {
            "name": "Zoning Polygons",
            "description": "Zoning district boundaries",
            "url": "https://gisdata-arlgis.opendata.arcgis.com/api/download/v1/items/5665fa97c4b5412fb79eb5ad70b968d6/geojson?layers=0",
            "filename": "zoning.geojson"
        },
        "glup": {
            "name": "General Land Use Plan",
            "description": "GLUP designations and sector data",
            "url": "https://gisdata-arlgis.opendata.arcgis.com/api/download/v1/items/c2599c5de0f84e2a9b7a1e5c3d0f8b6a/geojson?layers=0",
            "filename": "glup.geojson"
        },
        "building_heights": {
            "name": "Building Height Polygons",
            "description": "Building footprint outlines with elevation/height data from planimetric updates",
            "url": "https://gisdata-arlgis.opendata.arcgis.com/api/download/v1/items/3248008859c34cfaa7cac22f1273fdd3/geojson?layers=0",
            "filename": "building_heights.geojson"
        },
        "civic_associations": {
            "name": "Civic Association Polygons",
            "description": "Polygon boundaries for Arlington County civic associations (neighborhoods)",
            "url": "https://gisdata-arlgis.opendata.arcgis.com/api/download/v1/items/a8259221e70147cdbfe5714725512b50/geojson?layers=0",
            "filename": "civic_associations.geojson"
        }
    }

    # Arlington Open Data API endpoints (paginated JSON)
    # These use $top/$skip OData-style pagination
    API_DATASETS = {
        "property": {
            "name": "Real Estate Property",
            "description": "Property attributes including gross floor area, stories, year built, and use codes",
            "url": "https://datahub-v2.arlingtonva.us/api/RealEstate/Property",
            "filename": "property.json",
            "page_size": 10000
        },
        "assessment": {
            "name": "Real Estate Assessment",
            "description": "Assessment values including land, improvement, and total values (current year only)",
            "url": "https://datahub-v2.arlingtonva.us/api/RealEstate/Assessment",
            "filename": "assessment.json",
            "page_size": 10000,
            "filter": "assessmentDate ge 2025-01-01T00:00:00.000Z"
        }
    }
    
    def __init__(self, data_dir: str | Path = "data/raw"):
        """
        Initialize the downloader.
        
        Args:
            data_dir: Directory to store downloaded data files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def download_dataset(
        self, 
        dataset_key: str, 
        force: bool = False,
        timeout: int = 300
    ) -> Path:
        """
        Download a single dataset from the Open Data Portal.
        
        Args:
            dataset_key: Key identifying the dataset ('parcels', 'zoning', 'glup')
            force: If True, re-download even if file exists
            timeout: Request timeout in seconds (default 300 for large files)
            
        Returns:
            Path to the downloaded file
            
        Raises:
            ValueError: If dataset_key is not recognized
            requests.RequestException: If download fails
        """
        if dataset_key not in self.DATASETS:
            raise ValueError(
                f"Unknown dataset: {dataset_key}. "
                f"Available datasets: {list(self.DATASETS.keys())}"
            )
        
        dataset = self.DATASETS[dataset_key]
        output_path = self.data_dir / dataset["filename"]
        
        # Check if file already exists
        if output_path.exists() and not force:
            logger.info(f"Dataset '{dataset_key}' already exists at {output_path}")
            return output_path
        
        logger.info(f"Downloading {dataset['name']}...")
        logger.info(f"URL: {dataset['url']}")
        
        try:
            response = requests.get(dataset["url"], timeout=timeout, stream=True)
            response.raise_for_status()
            
            # Write to file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Verify it's valid GeoJSON by attempting to load it
            gdf = gpd.read_file(output_path)
            logger.info(
                f"Successfully downloaded {dataset['name']}: "
                f"{len(gdf)} features"
            )
            
            # Save metadata
            self._save_metadata(dataset_key, len(gdf))
            
            return output_path
            
        except requests.RequestException as e:
            logger.error(f"Failed to download {dataset['name']}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing downloaded data: {e}")
            # Clean up partial download
            if output_path.exists():
                output_path.unlink()
            raise
    
    def download_api_dataset(
        self,
        dataset_key: str,
        force: bool = False,
        timeout: int = 120
    ) -> Path:
        """
        Download a dataset from the Arlington Open Data REST API.

        These endpoints use OData-style $top/$skip pagination. All pages
        are fetched and combined into a single JSON file.

        Args:
            dataset_key: Key identifying the API dataset ('property', 'assessment')
            force: If True, re-download even if file exists
            timeout: Request timeout in seconds per page

        Returns:
            Path to the downloaded JSON file

        Raises:
            ValueError: If dataset_key is not recognized
            requests.RequestException: If download fails
        """
        if dataset_key not in self.API_DATASETS:
            raise ValueError(
                f"Unknown API dataset: {dataset_key}. "
                f"Available: {list(self.API_DATASETS.keys())}"
            )

        dataset = self.API_DATASETS[dataset_key]
        output_path = self.data_dir / dataset["filename"]

        if output_path.exists() and not force:
            logger.info(f"API dataset '{dataset_key}' already exists at {output_path}")
            return output_path

        logger.info(f"Downloading {dataset['name']} (paginated API)...")

        page_size = dataset["page_size"]
        odata_filter = dataset.get("filter", "")
        all_records = []
        skip = 0

        try:
            while True:
                url = f"{dataset['url']}?$top={page_size}&$skip={skip}"
                if odata_filter:
                    url += f"&$filter={odata_filter}"
                logger.info(f"Fetching records {skip} to {skip + page_size}...")

                response = requests.get(url, timeout=timeout)
                response.raise_for_status()

                page = response.json()
                if not page:
                    break

                all_records.extend(page)
                logger.info(f"  Retrieved {len(page)} records (total: {len(all_records)})")

                if len(page) < page_size:
                    break

                skip += page_size

            with open(output_path, 'w') as f:
                json.dump(all_records, f)

            logger.info(
                f"Successfully downloaded {dataset['name']}: "
                f"{len(all_records)} records"
            )

            self._save_metadata(dataset_key, len(all_records))
            return output_path

        except requests.RequestException as e:
            logger.error(f"Failed to download {dataset['name']}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing API data: {e}")
            if output_path.exists():
                output_path.unlink()
            raise

    def download_all(self, force: bool = False) -> dict[str, Path]:
        """
        Download all required datasets (GIS and API).

        Args:
            force: If True, re-download even if files exist

        Returns:
            Dictionary mapping dataset keys to file paths
        """
        paths = {}
        for dataset_key in self.DATASETS:
            try:
                paths[dataset_key] = self.download_dataset(dataset_key, force=force)
            except Exception as e:
                logger.error(f"Failed to download {dataset_key}: {e}")
                paths[dataset_key] = None

        for dataset_key in self.API_DATASETS:
            try:
                paths[dataset_key] = self.download_api_dataset(dataset_key, force=force)
            except Exception as e:
                logger.error(f"Failed to download {dataset_key}: {e}")
                paths[dataset_key] = None

        return paths
    
    def _save_metadata(self, dataset_key: str, feature_count: int) -> None:
        """Save download metadata for tracking data freshness."""
        metadata_path = self.data_dir / "download_metadata.json"

        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
        else:
            metadata = {}

        all_datasets = {**self.DATASETS, **self.API_DATASETS}
        metadata[dataset_key] = {
            "downloaded_at": datetime.now().isoformat(),
            "feature_count": feature_count,
            "source_url": all_datasets[dataset_key]["url"]
        }

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def get_download_info(self) -> dict:
        """
        Get information about downloaded datasets.
        
        Returns:
            Dictionary with download metadata for each dataset
        """
        metadata_path = self.data_dir / "download_metadata.json"
        
        if not metadata_path.exists():
            return {"status": "No datasets downloaded yet"}
        
        with open(metadata_path, 'r') as f:
            return json.load(f)
    
    def load_dataset(self, dataset_key: str) -> gpd.GeoDataFrame | pd.DataFrame:
        """
        Load a previously downloaded dataset.

        GIS datasets are returned as GeoDataFrames.
        API datasets are returned as DataFrames.

        Args:
            dataset_key: Key identifying the dataset

        Returns:
            GeoDataFrame for GIS datasets, DataFrame for API datasets

        Raises:
            ValueError: If dataset_key is not recognized
            FileNotFoundError: If dataset hasn't been downloaded
        """
        if dataset_key in self.DATASETS:
            filepath = self.data_dir / self.DATASETS[dataset_key]["filename"]
            if not filepath.exists():
                raise FileNotFoundError(
                    f"Dataset '{dataset_key}' not found. "
                    f"Run download_dataset('{dataset_key}') first."
                )
            return gpd.read_file(filepath)

        if dataset_key in self.API_DATASETS:
            filepath = self.data_dir / self.API_DATASETS[dataset_key]["filename"]
            if not filepath.exists():
                raise FileNotFoundError(
                    f"API dataset '{dataset_key}' not found. "
                    f"Run download_api_dataset('{dataset_key}') first."
                )
            with open(filepath, 'r') as f:
                return pd.DataFrame(json.load(f))

        raise ValueError(
            f"Unknown dataset: {dataset_key}. "
            f"Available: {list(self.DATASETS.keys()) + list(self.API_DATASETS.keys())}"
        )


# Convenience function for quick downloads
def download_arlington_data(
    data_dir: str | Path = "data/raw",
    force: bool = False
) -> dict[str, Path]:
    """
    Convenience function to download all Arlington County GIS data.
    
    Args:
        data_dir: Directory to store downloaded files
        force: If True, re-download even if files exist
        
    Returns:
        Dictionary mapping dataset keys to file paths
    """
    downloader = ArlingtonDataDownloader(data_dir)
    return downloader.download_all(force=force)
