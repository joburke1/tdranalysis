"""
Anomaly Check Runner
====================

Loads analysis results for a neighborhood and runs automated anomaly
detection to flag data quality issues.

Produces two output files alongside the existing analysis results:
  anomaly_report.csv    — one row per parcel with quality tier and flags
  anomaly_summary.txt   — human-readable counts, flag frequencies, and impact

Usage
-----
# Run on Alcova Heights (default):
    python scripts/run_anomaly_check.py

# Run on a specific neighborhood:
    python scripts/run_anomaly_check.py --neighborhood "Lyon Park"

# Specify a custom results directory:
    python scripts/run_anomaly_check.py --results-dir data/results/alcova_heights

# Suppress per-parcel detail in console output:
    python scripts/run_anomaly_check.py --quiet
"""

from __future__ import annotations

import argparse
import logging
import sys
import textwrap
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("run_anomaly_check")


def _find_analysis_csv(results_dir: Path, neighborhood: str | None) -> Path:
    """Locate the analysis CSV for a neighborhood results directory."""
    if neighborhood:
        safe = neighborhood.replace(" ", "_").lower()
        candidate = results_dir / safe / f"{safe}_analysis.csv"
        if candidate.exists():
            return candidate

    # Try to find any *_analysis.csv in the directory
    matches = list(results_dir.glob("*_analysis.csv"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.warning(
            f"Multiple analysis CSVs found in {results_dir}; "
            "use --neighborhood to specify which one. "
            f"Using: {matches[0].name}"
        )
        return matches[0]

    # Try one level down
    for subdir in sorted(results_dir.iterdir()):
        if subdir.is_dir():
            sub_matches = list(subdir.glob("*_analysis.csv"))
            if sub_matches:
                return sub_matches[0]

    raise FileNotFoundError(
        f"No *_analysis.csv found under {results_dir}. "
        "Run the analysis first with scripts/run_analysis.py."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run anomaly detection on analysis results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/run_anomaly_check.py
              python scripts/run_anomaly_check.py --neighborhood "Alcova Heights"
              python scripts/run_anomaly_check.py --results-dir data/results/alcova_heights
        """),
    )
    parser.add_argument(
        "--neighborhood", metavar="NAME",
        default="Alcova Heights",
        help='Neighborhood name (default: "Alcova Heights")',
    )
    parser.add_argument(
        "--results-dir", metavar="PATH",
        default="data/results",
        help="Base results directory (default: data/results)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-parcel detail in console output",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    import pandas as pd
    from src.analysis.anomaly_detection import detect_anomalies, summarize_anomalies

    # --- Locate input CSV ---
    results_base = (_PROJECT_ROOT / args.results_dir).resolve()
    try:
        csv_path = _find_analysis_csv(results_base, args.neighborhood)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    output_dir = csv_path.parent
    logger.info(f"Loading analysis results from: {csv_path}")

    df = pd.read_csv(csv_path, dtype={"parcel_id": str})
    logger.info(f"Loaded {len(df):,} parcels")

    # --- Run anomaly detection ---
    anomaly_df = detect_anomalies(df)

    # --- Save anomaly report CSV ---
    report_path = output_dir / "anomaly_report.csv"
    anomaly_df.to_csv(report_path, index=False)
    logger.info(f"Saved anomaly report: {report_path}")

    # --- Build and save summary ---
    summary = summarize_anomalies(df, anomaly_df)
    summary_path = output_dir / "anomaly_summary.txt"
    summary_path.write_text(summary, encoding="utf-8")
    logger.info(f"Saved anomaly summary: {summary_path}")

    # --- Console output ---
    if not args.quiet:
        print(f"\n{'='*60}")
        print(f"  Anomaly Report: {args.neighborhood}")
        print(f"{'='*60}")
        print(summary)
    else:
        # Brief summary only
        tier_counts = anomaly_df["quality_tier"].value_counts()
        print(
            f"\nAnomaly check complete for '{args.neighborhood}':\n"
            f"  auto-exclude:    {tier_counts.get('auto-exclude', 0):>5,}\n"
            f"  flag-for-review: {tier_counts.get('flag-for-review', 0):>5,}\n"
            f"  clean:           {tier_counts.get('clean', 0):>5,}\n"
            f"\nSee {report_path} and {summary_path}"
        )


if __name__ == "__main__":
    main()
