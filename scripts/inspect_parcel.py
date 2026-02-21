"""
Parcel Inspector CLI
====================

Command-line tool for inspecting a single parcel through the full
analysis pipeline, surfacing every intermediate value.

Usage examples::

    python scripts/inspect_parcel.py --parcel-id "06017024"
    python scripts/inspect_parcel.py --parcel-id "06017024" --neighborhood "Lyon Park"
    python scripts/inspect_parcel.py --parcel-id "06017024" --output report.txt
    python scripts/inspect_parcel.py --parcel-id "06017024" --json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root setup
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("inspect_parcel")


def _safe_label(label: str) -> str:
    """Convert a neighborhood label to a filesystem-safe directory name."""
    return re.sub(r"[^\w-]", "_", label).lower()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a single parcel through the full analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/inspect_parcel.py --parcel-id "06017024"
              python scripts/inspect_parcel.py --parcel-id "06017024" --neighborhood "Lyon Park"
              python scripts/inspect_parcel.py --parcel-id "06017024" --json
              python scripts/inspect_parcel.py --parcel-id "06017024" --output report.txt
        """),
    )

    parser.add_argument(
        "--parcel-id", required=True,
        help="Parcel identifier (RPCMSTR) to inspect",
    )
    parser.add_argument(
        "--neighborhood", metavar="NAME",
        help="Neighborhood name for rate calibration (derived from parcel if omitted)",
    )
    parser.add_argument(
        "--output", metavar="FILE",
        help="Write report to a file instead of stdout",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output machine-readable JSON instead of formatted report",
    )

    # Paths
    parser.add_argument(
        "--processed-path", default="data/processed/parcels_enriched.gpkg",
        help="Path to processed GeoPackage (default: data/processed/parcels_enriched.gpkg)",
    )
    parser.add_argument(
        "--config-dir", default="config",
        help="Config directory (default: config)",
    )
    parser.add_argument(
        "--output-dir", default="data/results",
        help="Results directory for spot_checks.csv lookup (default: data/results)",
    )

    # Processing control
    parser.add_argument(
        "--force-process", action="store_true",
        help="Re-process raw data instead of loading from --processed-path",
    )

    # Logging
    parser.add_argument(
        "--log-level", default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: WARNING for clean output)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Resolve paths
    processed_path = (_PROJECT_ROOT / args.processed_path).resolve()
    config_dir = (_PROJECT_ROOT / args.config_dir).resolve()
    output_dir = (_PROJECT_ROOT / args.output_dir).resolve()

    # Load enriched data
    import geopandas as gpd
    import pandas as pd

    if not processed_path.exists() and not args.force_process:
        logger.error(
            "Processed data not found at %s. "
            "Run the analysis pipeline first or use --force-process.",
            processed_path,
        )
        sys.exit(1)

    if args.force_process or not processed_path.exists():
        # Re-process from raw data
        raw_dir = (_PROJECT_ROOT / "data/raw").resolve()
        if not (raw_dir / "parcels.geojson").exists():
            logger.error("Raw data not found in %s. Run run_analysis.py first.", raw_dir)
            sys.exit(1)

        logger.info("Re-processing raw data...")
        from src.data import DataProcessor

        parcels = gpd.read_file(raw_dir / "parcels.geojson")
        zoning = gpd.read_file(raw_dir / "zoning.geojson")

        glup = None
        glup_path = raw_dir / "glup.geojson"
        if glup_path.exists():
            glup = gpd.read_file(glup_path)

        civic_associations = None
        ca_path = raw_dir / "civic_associations.geojson"
        if ca_path.exists():
            civic_associations = gpd.read_file(ca_path)

        property_df = None
        property_path = raw_dir / "property.json"
        if property_path.exists():
            with open(property_path, encoding="utf-8") as f:
                property_df = pd.DataFrame(json.load(f))

        assessment_df = None
        assessment_path = raw_dir / "assessment.json"
        if assessment_path.exists():
            with open(assessment_path, encoding="utf-8") as f:
                assessment_df = pd.DataFrame(json.load(f))

        processor = DataProcessor(
            parcels_gdf=parcels,
            zoning_gdf=zoning,
            glup_gdf=glup,
            property_df=property_df,
            assessment_df=assessment_df,
            civic_associations_gdf=civic_associations,
        )
        enriched = processor.process_all(output_path=processed_path)
    else:
        logger.info("Loading processed data from %s...", processed_path)
        enriched = gpd.read_file(processed_path)

    # Determine neighborhood for rate calibration
    neighborhood_gdf = None
    neighborhood_output_dir = None

    if args.neighborhood:
        neighborhood = args.neighborhood
    else:
        # Try to derive from parcel's civic_association
        mask = enriched["RPCMSTR"].astype(str) == str(args.parcel_id)
        if mask.any() and "civic_association" in enriched.columns:
            ca = enriched.loc[mask].iloc[0].get("civic_association")
            if ca and not (isinstance(ca, float) and pd.isna(ca)):
                neighborhood = str(ca)
                logger.info("Derived neighborhood: %s", neighborhood)
            else:
                neighborhood = None
        else:
            neighborhood = None

    if neighborhood and "civic_association" in enriched.columns:
        neighborhood_gdf = enriched[enriched["civic_association"] == neighborhood].copy()
        neighborhood_output_dir = output_dir / _safe_label(neighborhood)
        if len(neighborhood_gdf) == 0:
            logger.warning(
                "No parcels found for neighborhood '%s'; "
                "using full dataset for rate calibration.",
                neighborhood,
            )
            neighborhood_gdf = None
            neighborhood_output_dir = None

    # Run inspection
    from src.analysis.inspector import inspect_parcel

    result = inspect_parcel(
        parcel_id=args.parcel_id,
        enriched_gdf=enriched,
        config_dir=config_dir,
        output_dir=neighborhood_output_dir,
        neighborhood_gdf=neighborhood_gdf,
    )

    # Output
    if args.json_output:
        output_text = json.dumps(result.to_dict(), indent=2, default=str)
    else:
        output_text = result.report()

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"Report written to {out_path}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
