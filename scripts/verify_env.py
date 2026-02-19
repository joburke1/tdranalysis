"""
Environment Verification Script
Arlington Zoning Analyzer

Run this before the first analysis to confirm that all prerequisites are met.

Usage:
    python scripts/verify_env.py
"""

import sys
import os

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

errors = []
warnings = []


def check(label: str, condition: bool, fail_msg: str, warn: bool = False) -> None:
    tag = WARN if warn else FAIL
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {tag}  {label}: {fail_msg}")
        if warn:
            warnings.append(fail_msg)
        else:
            errors.append(fail_msg)


# ---------------------------------------------------------------------------
# Python version
# ---------------------------------------------------------------------------

print("\n=== Python Version ===")
major, minor = sys.version_info[:2]
check(
    f"Python {major}.{minor}",
    (major, minor) >= (3, 11),
    f"Python 3.11+ required; found {major}.{minor}",
)

# ---------------------------------------------------------------------------
# Required packages
# ---------------------------------------------------------------------------

print("\n=== Required Packages ===")

REQUIRED = [
    ("geopandas", "1.1.0"),
    ("shapely", "2.1.0"),
    ("pyproj", "3.7.0"),
    ("pandas", "3.0.0"),
    ("numpy", "2.4.0"),
    ("requests", "2.32.0"),
    ("pydantic", "2.12.0"),
]

for pkg_name, min_version in REQUIRED:
    try:
        import importlib
        mod = importlib.import_module(pkg_name)
        installed = getattr(mod, "__version__", "unknown")
        check(f"{pkg_name} >= {min_version} (installed: {installed})", True, "")
    except ImportError:
        check(f"{pkg_name} >= {min_version}", False, f"{pkg_name} not installed")

# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------

print("\n=== Project Structure ===")

# Find project root (parent of scripts/)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)

check(
    f"Project root found: {project_root}",
    os.path.isdir(project_root),
    "Cannot determine project root",
)

# ---------------------------------------------------------------------------
# Configuration files
# ---------------------------------------------------------------------------

print("\n=== Configuration Files ===")

config_dir = os.path.join(project_root, "config")
required_configs = [
    "residential_districts.json",
    "setback_rules.json",
    "valuation_params.json",
]
for cfg in required_configs:
    path = os.path.join(config_dir, cfg)
    check(f"config/{cfg}", os.path.isfile(path), f"Missing: {path}")

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

print("\n=== Data Directory ===")

data_dir = os.path.join(project_root, "data")
raw_dir = os.path.join(data_dir, "raw")
processed_dir = os.path.join(data_dir, "processed")

check("data/ directory exists", os.path.isdir(data_dir), f"Missing: {data_dir}")
check("data/raw/ directory exists", os.path.isdir(raw_dir), f"Missing: {raw_dir}", warn=True)

# Check for already-downloaded data
raw_datasets = {
    "parcels.geojson": "Parcel polygons (GIS)",
    "zoning.geojson": "Zoning districts (GIS)",
    "civic_associations.geojson": "Civic association boundaries (GIS)",
    "property.json": "Property attributes (API)",
    "assessment.json": "Assessment values (API)",
}

print("\n=== Downloaded Datasets ===")
if os.path.isdir(raw_dir):
    for filename, description in raw_datasets.items():
        path = os.path.join(raw_dir, filename)
        exists = os.path.isfile(path)
        if exists:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  {PASS}  {filename} ({description}) — {size_mb:.1f} MB")
        else:
            print(f"  {WARN}  {filename} ({description}) — not yet downloaded")
            warnings.append(f"{filename} not downloaded; run with --download first")

    # Check metadata for data freshness
    metadata_path = os.path.join(raw_dir, "download_metadata.json")
    if os.path.isfile(metadata_path):
        import json
        from datetime import datetime, timezone
        with open(metadata_path) as f:
            meta = json.load(f)
        print("\n  Data freshness:")
        for key, info in meta.items():
            downloaded_at = info.get("downloaded_at", "unknown")
            if downloaded_at != "unknown":
                try:
                    dt = datetime.fromisoformat(downloaded_at)
                    age_days = (datetime.now() - dt).days
                    freshness = f"{age_days} days old"
                    if age_days > 90:
                        print(f"    {WARN}  {key}: {freshness} (consider refreshing)")
                        warnings.append(f"{key} data is {age_days} days old")
                    else:
                        print(f"    {PASS}  {key}: {freshness}")
                except Exception:
                    print(f"    {WARN}  {key}: downloaded at {downloaded_at}")
else:
    print(f"  {WARN}  data/raw/ does not exist; no datasets downloaded yet")

# ---------------------------------------------------------------------------
# Source package importable
# ---------------------------------------------------------------------------

print("\n=== Source Package ===")

sys.path.insert(0, project_root)
try:
    from src.data import ArlingtonDataDownloader, DataProcessor  # noqa: F401
    check("src.data importable", True, "")
except ImportError as e:
    check("src.data importable", False, str(e))

try:
    from src.analysis import (  # noqa: F401
        analyze_development_potential,
        calculate_available_rights,
        estimate_valuation_geodataframe,
    )
    check("src.analysis importable", True, "")
except ImportError as e:
    check("src.analysis importable", False, str(e))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 50)
if errors:
    print(f"ENVIRONMENT CHECK FAILED — {len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    print("\nResolve the errors above before running the analysis.")
    sys.exit(1)
elif warnings:
    print(f"ENVIRONMENT OK — {len(warnings)} warning(s):")
    for w in warnings:
        print(f"  - {w}")
    print(
        "\nThe environment is usable. Run 'python scripts/run_analysis.py --help' to start."
    )
else:
    print("ENVIRONMENT OK — all checks passed.")
    print("\nRun 'python scripts/run_analysis.py --help' to start.")
