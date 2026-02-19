"""
Arlington Zoning Analyzer — Analysis Runner
============================================

Executes the full analysis pipeline for one or all civic association
neighborhoods in Arlington County, VA:

  1. Download GIS + property/assessment data (cached)
  2. Process: spatial join parcels → zoning + neighborhoods + property/assessment
  3. Filter to the requested neighborhood(s)
  4. Run analysis: development potential → current built → available rights → valuation
  5. Save results as GeoPackage + CSV and print a summary

Usage examples
--------------
# Verify environment first:
    python scripts/verify_env.py

# List available neighborhoods (after data is downloaded):
    python scripts/run_analysis.py --list-neighborhoods

# Run MVP: single neighborhood:
    python scripts/run_analysis.py --neighborhood "Lyon Park"

# Run all neighborhoods (batch mode):
    python scripts/run_analysis.py --all-neighborhoods

# Force re-download of source data before running:
    python scripts/run_analysis.py --neighborhood "Lyon Park" --force-refresh

# Check data freshness without running analysis:
    python scripts/run_analysis.py --check-data

# Use a custom data or output directory:
    python scripts/run_analysis.py --neighborhood "Lyon Park" \\
        --data-dir data/raw --output-dir data/results

# Skip the download step (use cached data):
    python scripts/run_analysis.py --neighborhood "Lyon Park" --skip-download
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
from datetime import datetime
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
logger = logging.getLogger("run_analysis")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_data_freshness(raw_dir: Path) -> None:
    """Print data freshness report from download_metadata.json."""
    metadata_path = raw_dir / "download_metadata.json"
    if not metadata_path.exists():
        logger.warning("No download metadata found; data may not have been downloaded yet.")
        return

    with open(metadata_path) as f:
        meta = json.load(f)

    print("\n=== Data Freshness ===")
    for key, info in meta.items():
        downloaded_at = info.get("downloaded_at", "unknown")
        feature_count = info.get("feature_count", "?")
        if downloaded_at != "unknown":
            try:
                dt = datetime.fromisoformat(downloaded_at)
                age_days = (datetime.now() - dt).days
                flag = " [STALE — consider --force-refresh]" if age_days > 90 else ""
                print(f"  {key:<25} {age_days:>4} days old   {feature_count:>8,} records{flag}")
            except Exception:
                print(f"  {key:<25} downloaded: {downloaded_at}  records: {feature_count}")
        else:
            print(f"  {key:<25} downloaded: unknown")
    print()


def _warn_if_stale(raw_dir: Path, threshold_days: int = 90) -> None:
    """Log a warning if any dataset is older than threshold_days."""
    metadata_path = raw_dir / "download_metadata.json"
    if not metadata_path.exists():
        return
    with open(metadata_path) as f:
        meta = json.load(f)
    for key, info in meta.items():
        downloaded_at = info.get("downloaded_at", "")
        if downloaded_at:
            try:
                dt = datetime.fromisoformat(downloaded_at)
                age_days = (datetime.now() - dt).days
                if age_days > threshold_days:
                    logger.warning(
                        f"Dataset '{key}' is {age_days} days old. "
                        "Use --force-refresh to re-download."
                    )
            except Exception:
                pass


def _download_data(raw_dir: Path, force: bool = False) -> None:
    """Download all required datasets."""
    from src.data import ArlingtonDataDownloader

    logger.info(f"Downloading data to {raw_dir} (force={force})...")
    downloader = ArlingtonDataDownloader(raw_dir)
    paths = downloader.download_all(force=force)

    success = [k for k, v in paths.items() if v is not None]
    failed = [k for k, v in paths.items() if v is None]

    logger.info(f"Downloaded: {', '.join(success)}")
    if failed:
        logger.warning(f"Failed to download: {', '.join(failed)}")


def _process_data(raw_dir: Path, processed_path: Path) -> "gpd.GeoDataFrame":
    """Load raw data and run the processing pipeline."""
    import geopandas as gpd
    import pandas as pd
    from src.data import DataProcessor
    import json as _json

    logger.info("Loading datasets...")
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
        logger.info(f"Loaded {len(civic_associations)} civic association polygons")
    else:
        logger.warning(
            "civic_associations.geojson not found; neighborhood filtering unavailable. "
            "Re-run without --skip-download to fetch this dataset."
        )

    property_df = None
    property_path = raw_dir / "property.json"
    if property_path.exists():
        logger.info("Loading property data...")
        with open(property_path) as f:
            property_df = pd.DataFrame(_json.load(f))

    assessment_df = None
    assessment_path = raw_dir / "assessment.json"
    if assessment_path.exists():
        logger.info("Loading assessment data...")
        with open(assessment_path) as f:
            assessment_df = pd.DataFrame(_json.load(f))

    processor = DataProcessor(
        parcels_gdf=parcels,
        zoning_gdf=zoning,
        glup_gdf=glup,
        property_df=property_df,
        assessment_df=assessment_df,
        civic_associations_gdf=civic_associations,
    )

    logger.info("Processing data (spatial joins)...")
    enriched = processor.process_all(output_path=processed_path)
    logger.info(f"Processed {len(enriched):,} parcels → saved to {processed_path}")
    return enriched


def _load_processed(processed_path: Path) -> "gpd.GeoDataFrame":
    """Load previously processed enriched parcels."""
    import geopandas as gpd
    logger.info(f"Loading processed data from {processed_path}...")
    return gpd.read_file(processed_path)


def _list_neighborhoods(enriched: "gpd.GeoDataFrame") -> list[str]:
    """Return sorted list of civic association names present in the data."""
    if "civic_association" not in enriched.columns:
        return []
    names = (
        enriched["civic_association"]
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(names)


def _filter_to_neighborhood(
    enriched: "gpd.GeoDataFrame", neighborhood: str
) -> "gpd.GeoDataFrame":
    """Filter enriched GeoDataFrame to a single civic association name."""
    if "civic_association" not in enriched.columns:
        raise ValueError(
            "No 'civic_association' column found. "
            "Ensure civic_associations.geojson was downloaded and processed."
        )
    filtered = enriched[enriched["civic_association"] == neighborhood].copy()
    if len(filtered) == 0:
        raise ValueError(
            f"No parcels found for neighborhood '{neighborhood}'. "
            "Use --list-neighborhoods to see available names."
        )
    return filtered


def _run_analysis(
    parcels: "gpd.GeoDataFrame",
    config_dir: Path,
    label: str,
) -> "gpd.GeoDataFrame":
    """Run the full 4-stage analysis pipeline on a parcel GeoDataFrame."""
    from src.analysis import estimate_valuation_geodataframe

    residential = parcels[parcels.get("is_residential_zoning", False) == True].copy()  # noqa: E712
    total = len(parcels)
    res_count = len(residential)

    logger.info(
        f"[{label}] Analyzing {res_count:,} residential parcels "
        f"(of {total:,} total)..."
    )

    if res_count == 0:
        logger.warning(f"[{label}] No residential parcels found; skipping analysis.")
        return parcels

    result_gdf = estimate_valuation_geodataframe(
        gdf=residential,
        config_dir=config_dir,
    )
    logger.info(f"[{label}] Analysis complete.")
    return result_gdf


def _save_results(
    result_gdf: "gpd.GeoDataFrame",
    output_dir: Path,
    label: str,
) -> None:
    """Save analysis results to GeoPackage and CSV."""
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)

    safe_label = label.replace(" ", "_").replace("/", "-").lower()

    gpkg_path = output_dir / f"{safe_label}_analysis.gpkg"
    csv_path = output_dir / f"{safe_label}_analysis.csv"
    summary_path = output_dir / f"{safe_label}_summary.txt"

    # Save GeoPackage
    result_gdf.to_file(gpkg_path, driver="GPKG")
    logger.info(f"  Saved GeoPackage: {gpkg_path}")

    # Save flat CSV (drop geometry for CSV)
    csv_df = result_gdf.drop(columns=["geometry"], errors="ignore")
    csv_df.to_csv(csv_path, index=False)
    logger.info(f"  Saved CSV:        {csv_path}")

    # Generate and save summary
    summary = _build_summary(result_gdf, label)
    summary_path.write_text(summary, encoding="utf-8")
    logger.info(f"  Saved summary:    {summary_path}")

    print(f"\n{'='*60}")
    print(f"  Results for: {label}")
    print(f"{'='*60}")
    print(summary)


def _build_summary(result_gdf: "gpd.GeoDataFrame", label: str) -> str:
    """Build a human-readable summary of analysis results."""
    import numpy as np

    lines = [
        f"Analysis Summary: {label}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
    ]

    total = len(result_gdf)
    lines.append(f"\nTotal residential parcels analyzed: {total:,}")

    # Conformance
    if "is_conforming" in result_gdf.columns:
        conforming = result_gdf["is_conforming"].sum()
        lines.append(f"Conforming parcels: {conforming:,} ({conforming/total*100:.1f}%)")

    # Zoning breakdown
    if "zoning_district" in result_gdf.columns:
        zones = result_gdf["zoning_district"].value_counts()
        lines.append("\nZoning district breakdown:")
        for zone, count in zones.head(10).items():
            lines.append(f"  {zone:<12} {count:>6,} parcels")

    # Available rights
    if "available_gfa_sf" in result_gdf.columns:
        avail = result_gdf["available_gfa_sf"].dropna()
        if len(avail) > 0:
            lines.extend([
                "\nAvailable GFA Capacity (residential parcels with data):",
                f"  Parcels with data:  {len(avail):,}",
                f"  Total available SF: {avail.clip(lower=0).sum():>15,.0f} sf",
                f"  Median per parcel:  {avail.median():>15,.0f} sf",
                f"  Mean per parcel:    {avail.mean():>15,.0f} sf",
            ])

        underdeveloped = result_gdf.get("is_underdeveloped", None)
        if underdeveloped is not None:
            n_under = (underdeveloped == True).sum()  # noqa: E712
            lines.append(f"  Underdeveloped:     {n_under:>15,} parcels")

        overdeveloped = result_gdf.get("is_overdeveloped", None)
        if overdeveloped is not None:
            n_over = (overdeveloped == True).sum()  # noqa: E712
            lines.append(f"  Overdeveloped:      {n_over:>15,} parcels")

    # Valuation
    if "estimated_value_low" in result_gdf.columns:
        valueable = result_gdf[result_gdf.get("valuation_is_valueable", False) == True]  # noqa: E712
        n_val = len(valueable)
        if n_val > 0:
            total_low = valueable["estimated_value_low"].sum()
            total_high = valueable["estimated_value_high"].sum()
            lines.extend([
                "\nValuation (parcels with positive available rights):",
                f"  Parcels valued:     {n_val:>15,}",
                f"  Aggregate low:      ${total_low:>14,.0f}",
                f"  Aggregate high:     ${total_high:>14,.0f}",
            ])

            # Confidence breakdown
            if "valuation_confidence" in result_gdf.columns:
                conf_counts = result_gdf["valuation_confidence"].value_counts()
                lines.append("  Confidence levels:")
                for level, count in conf_counts.items():
                    lines.append(f"    {level:<16} {count:>6,}")

    lines.append("\n" + "=" * 60)
    lines.append(
        "DISCLAIMER: Valuation estimates are for policy analysis only,\n"
        "not property appraisals. Calibrate market parameters before use."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Arlington Zoning Analyzer — Analysis Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/run_analysis.py --list-neighborhoods
              python scripts/run_analysis.py --neighborhood "Lyon Park"
              python scripts/run_analysis.py --all-neighborhoods
              python scripts/run_analysis.py --check-data
              python scripts/run_analysis.py --neighborhood "Lyon Park" --force-refresh
        """),
    )

    # Mode flags (mutually exclusive)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--neighborhood", metavar="NAME",
        help="Run analysis for a single civic association neighborhood (MVP mode)"
    )
    mode.add_argument(
        "--all-neighborhoods", action="store_true",
        help="Run analysis for every civic association neighborhood (batch mode)"
    )
    mode.add_argument(
        "--list-neighborhoods", action="store_true",
        help="List available neighborhood names and exit (requires processed data)"
    )
    mode.add_argument(
        "--check-data", action="store_true",
        help="Report data freshness and exit"
    )

    # Paths
    parser.add_argument(
        "--data-dir", default="data/raw",
        help="Directory for raw downloaded data (default: data/raw)"
    )
    parser.add_argument(
        "--processed-path", default="data/processed/parcels_enriched.gpkg",
        help="Path for the processed GeoPackage (default: data/processed/parcels_enriched.gpkg)"
    )
    parser.add_argument(
        "--output-dir", default="data/results",
        help="Output directory for analysis results (default: data/results)"
    )
    parser.add_argument(
        "--config-dir", default="config",
        help="Config directory containing zoning rules (default: config)"
    )

    # Download control
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Skip the download step and use cached data"
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Force re-download of all source datasets"
    )
    parser.add_argument(
        "--skip-process", action="store_true",
        help="Skip processing step and load from --processed-path directly"
    )

    # Logging
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Resolve paths relative to project root
    raw_dir = (_PROJECT_ROOT / args.data_dir).resolve()
    processed_path = (_PROJECT_ROOT / args.processed_path).resolve()
    output_dir = (_PROJECT_ROOT / args.output_dir).resolve()
    config_dir = (_PROJECT_ROOT / args.config_dir).resolve()

    # --check-data mode
    if args.check_data:
        _check_data_freshness(raw_dir)
        return

    # Ensure we have a mode selected
    if not args.neighborhood and not args.all_neighborhoods and not args.list_neighborhoods:
        parser.print_help()
        print(
            "\nError: Specify --neighborhood NAME, --all-neighborhoods, "
            "--list-neighborhoods, or --check-data"
        )
        sys.exit(1)

    # --- Step 1: Download ---
    if args.force_refresh:
        _download_data(raw_dir, force=True)
    elif not args.skip_download:
        # Check if any required data is missing; download if so
        required = [
            raw_dir / "parcels.geojson",
            raw_dir / "zoning.geojson",
            raw_dir / "civic_associations.geojson",
            raw_dir / "property.json",
            raw_dir / "assessment.json",
        ]
        missing = [p for p in required if not p.exists()]
        if missing:
            logger.info(
                f"Missing data files ({[p.name for p in missing]}); downloading..."
            )
            _download_data(raw_dir, force=False)
        else:
            logger.info("Data files present; skipping download (use --force-refresh to re-download)")
            _warn_if_stale(raw_dir)

    # --- Step 2: Process ---
    if args.skip_process and processed_path.exists():
        enriched = _load_processed(processed_path)
    else:
        if not (raw_dir / "parcels.geojson").exists():
            logger.error(
                f"parcels.geojson not found in {raw_dir}. "
                "Run without --skip-download to download data first."
            )
            sys.exit(1)
        enriched = _process_data(raw_dir, processed_path)

    # --list-neighborhoods mode
    if args.list_neighborhoods:
        neighborhoods = _list_neighborhoods(enriched)
        if not neighborhoods:
            print(
                "No civic_association column found in processed data.\n"
                "Ensure civic_associations.geojson was downloaded and re-run processing."
            )
            sys.exit(1)
        print(f"\nAvailable neighborhoods ({len(neighborhoods)}):")
        for name in neighborhoods:
            count = (enriched["civic_association"] == name).sum()
            print(f"  {name:<40} ({count:,} parcels)")
        return

    # --- Step 3+: Analysis ---
    if args.neighborhood:
        # MVP: single neighborhood
        neighborhood = args.neighborhood
        logger.info(f"Filtering to neighborhood: '{neighborhood}'")
        try:
            subset = _filter_to_neighborhood(enriched, neighborhood)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

        logger.info(f"Found {len(subset):,} parcels in '{neighborhood}'")
        result = _run_analysis(subset, config_dir, label=neighborhood)
        _save_results(result, output_dir / neighborhood.replace(" ", "_").lower(), neighborhood)

    elif args.all_neighborhoods:
        # Batch: all neighborhoods
        neighborhoods = _list_neighborhoods(enriched)
        if not neighborhoods:
            logger.error(
                "No civic_association column found. "
                "Cannot run batch mode without neighborhood data."
            )
            sys.exit(1)

        logger.info(f"Batch mode: processing {len(neighborhoods)} neighborhoods...")
        import pandas as pd

        all_results = []
        failed = []

        for i, neighborhood in enumerate(neighborhoods, 1):
            logger.info(f"[{i}/{len(neighborhoods)}] {neighborhood}")
            try:
                subset = _filter_to_neighborhood(enriched, neighborhood)
                result = _run_analysis(subset, config_dir, label=neighborhood)
                _save_results(
                    result,
                    output_dir / neighborhood.replace(" ", "_").lower(),
                    neighborhood,
                )
                all_results.append(result)
            except Exception as e:
                logger.error(f"Failed to process '{neighborhood}': {e}")
                failed.append(neighborhood)

        # Aggregate summary CSV
        if all_results:
            agg_df = pd.concat(
                [r.drop(columns=["geometry"], errors="ignore") for r in all_results],
                ignore_index=True,
            )
            agg_path = output_dir / "all_neighborhoods_combined.csv"
            output_dir.mkdir(parents=True, exist_ok=True)
            agg_df.to_csv(agg_path, index=False)
            logger.info(f"Saved combined results: {agg_path}")

        if failed:
            logger.warning(f"Failed neighborhoods ({len(failed)}): {', '.join(failed)}")

        print(f"\nBatch complete: {len(all_results)} succeeded, {len(failed)} failed.")


if __name__ == "__main__":
    main()
