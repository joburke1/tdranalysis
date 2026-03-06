"""
apply_corrections.py — Merge approved correction JSON files into spot_checks.csv
=================================================================================

Reads all JSON files under corrections/ and upserts rows into the appropriate
data/results/<neighborhood>/spot_checks.csv files. The operation is idempotent:
running it twice produces the same result.

Usage
-----
  # Apply all pending corrections:
  python scripts/apply_corrections.py

  # Apply corrections for one neighborhood only:
  python scripts/apply_corrections.py --neighborhood alcova_heights

  # Preview without writing (dry run):
  python scripts/apply_corrections.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


VALID_SPOT_CHECK_RESULTS = {"excluded", "confirmed", "reviewed"}

# Columns written to spot_checks.csv
SPOT_CHECK_COLS = [
    "parcel_id",
    "spot_check_result",
    "spot_check_notes",
    "reporter",
    "reported_date",
    "approved_by",
    "approved_date",
    "issue_number",
]

# Columns written to overrides.csv (structured field values for confirmed parcels)
OVERRIDE_COLS = [
    "parcel_id",
    "propertyClassTypeCode",
    "propertyClassTypeDsc",
    "grossFloorAreaSquareFeetQty",
    "propertyYearBuilt",
    "storyHeightCnt",
]


def load_corrections(corrections_dir: Path, neighborhood: str | None) -> list[dict]:
    """Load all correction JSON files, optionally filtered by neighborhood slug."""
    pattern = f"{neighborhood}/*.json" if neighborhood else "**/*.json"
    files = sorted(corrections_dir.glob(pattern))

    corrections = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            corrections.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  WARNING: Could not read {path}: {exc}", file=sys.stderr)

    return corrections


def apply_to_neighborhood(
    neighborhood_slug: str,
    records: list[dict],
    results_dir: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """Upsert correction records into a neighborhood's spot_checks.csv.

    Returns (applied, already_present) counts.
    """
    # Guard against path traversal: slugs must be word characters only.
    if not re.fullmatch(r"[\w-]+", neighborhood_slug):
        print(
            f"  ERROR: Skipping unsafe neighborhood slug: {neighborhood_slug!r}",
            file=sys.stderr,
        )
        return 0, 0

    sc_path = results_dir / neighborhood_slug / "spot_checks.csv"

    # Load existing records keyed by parcel_id
    existing: dict[str, dict] = {}
    if sc_path.exists():
        with sc_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row["parcel_id"]] = row

    applied = 0
    already_present = 0

    for rec in records:
        parcel_id = rec.get("parcel_id", "")
        if not parcel_id:
            print(f"  WARNING: Correction record missing parcel_id: {rec}", file=sys.stderr)
            continue

        result = rec.get("spot_check_result", "").lower()
        if result not in VALID_SPOT_CHECK_RESULTS:
            print(
                f"  WARNING: Parcel {parcel_id} has unknown spot_check_result "
                f"{result!r} (expected one of {sorted(VALID_SPOT_CHECK_RESULTS)}); skipping.",
                file=sys.stderr,
            )
            continue

        new_row = {
            "parcel_id":         parcel_id,
            "spot_check_result": result,
            "spot_check_notes":  rec.get("spot_check_notes", ""),
            "reporter":          rec.get("reporter", ""),
            "reported_date":     rec.get("reported_date", ""),
            "approved_by":       rec.get("approved_by", ""),
            "approved_date":     rec.get("approved_date", ""),
            "issue_number":      str(rec.get("issue_number", "")),
        }

        if parcel_id in existing:
            # Check if identical to avoid spurious "applied" counts
            old = {k: existing[parcel_id].get(k, "") for k in SPOT_CHECK_COLS}
            if old == new_row:
                already_present += 1
                continue

        existing[parcel_id] = new_row
        applied += 1

    if applied > 0 and not dry_run:
        sc_path.parent.mkdir(parents=True, exist_ok=True)
        with sc_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SPOT_CHECK_COLS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing.values())

    # Write overrides.csv for confirmed records that have an overrides dict.
    override_rows: list[dict] = []
    for rec in records:
        overrides = rec.get("overrides")
        if not overrides or not isinstance(overrides, dict):
            continue
        parcel_id = rec.get("parcel_id", "")
        if not parcel_id:
            continue
        row = {"parcel_id": parcel_id}
        for col in OVERRIDE_COLS[1:]:
            val = overrides.get(col)
            row[col] = str(val) if val is not None else ""
        override_rows.append(row)

    if override_rows and not dry_run:
        ov_path = results_dir / neighborhood_slug / "overrides.csv"
        ov_path.parent.mkdir(parents=True, exist_ok=True)
        # Upsert: load existing, merge by parcel_id, write back.
        existing_ov: dict[str, dict] = {}
        if ov_path.exists():
            with ov_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_ov[row["parcel_id"]] = row
        for row in override_rows:
            existing_ov[row["parcel_id"]] = row
        with ov_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OVERRIDE_COLS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing_ov.values())
        print(
            f"  {neighborhood_slug}: wrote {len(override_rows)} override record(s) "
            "to overrides.csv"
        )
    elif override_rows and dry_run:
        print(
            f"  {neighborhood_slug}: would write {len(override_rows)} override record(s) "
            "to overrides.csv (dry run)"
        )

    return applied, already_present


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge approved correction JSON files into spot_checks.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--neighborhood",
        metavar="SLUG",
        help="Apply corrections for this neighborhood slug only (e.g. alcova_heights)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing any files",
    )
    parser.add_argument(
        "--corrections-dir",
        metavar="DIR",
        default="corrections",
        help="Path to corrections directory (default: corrections/)",
    )
    parser.add_argument(
        "--results-dir",
        metavar="DIR",
        default="data/results",
        help="Path to pipeline results directory (default: data/results/)",
    )
    args = parser.parse_args()

    corrections_dir = Path(args.corrections_dir)
    results_dir     = Path(args.results_dir)

    if args.neighborhood and not re.fullmatch(r"[\w-]+", args.neighborhood):
        print(
            f"ERROR: --neighborhood must be a valid slug (letters, digits, underscores, "
            f"hyphens only): {args.neighborhood!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not corrections_dir.exists():
        print(f"ERROR: Corrections directory not found: {corrections_dir}", file=sys.stderr)
        sys.exit(1)

    corrections = load_corrections(corrections_dir, args.neighborhood)

    if not corrections:
        print("No correction files found.")
        return

    # Group by neighborhood slug
    by_neighborhood: dict[str, list[dict]] = defaultdict(list)
    for rec in corrections:
        slug = rec.get("neighborhood", "")
        if not slug:
            print(f"  WARNING: Record missing neighborhood field: {rec}", file=sys.stderr)
            continue
        by_neighborhood[slug].append(rec)

    total_applied  = 0
    total_present  = 0
    neighborhoods_affected = []

    for slug, records in sorted(by_neighborhood.items()):
        applied, present = apply_to_neighborhood(slug, records, results_dir, args.dry_run)
        total_applied  += applied
        total_present  += present
        if applied > 0:
            neighborhoods_affected.append(slug)
        status = "(dry run)" if args.dry_run else ""
        print(
            f"  {slug}: {applied} applied, {present} already present {status}".rstrip()
        )

    print()
    print(f"Total: {total_applied} corrections applied, {total_present} already present")
    if neighborhoods_affected:
        print(f"Affected neighborhoods: {', '.join(neighborhoods_affected)}")
        if not args.dry_run:
            print(
                "\nNext step: re-run the pipeline for each affected neighborhood, then "
                "regenerate and commit the map(s)."
            )
    else:
        print("No changes made.")


if __name__ == "__main__":
    main()
