#!/usr/bin/env python3
"""Cleanup eval reports older than 7 days.

Usage:
    python backend/scripts/cleanup_eval_reports.py [--dry-run] [--days 7]

Deletes JSON report files from backend/evals/reports/ that are older
than the specified number of days (default: 7).
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "evals" / "reports"


def find_old_reports(days: int) -> list[Path]:
    """Find report files older than `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()

    old_files = []
    if not REPORTS_DIR.exists():
        return old_files

    for f in REPORTS_DIR.glob("*.json"):
        if f.stat().st_mtime < cutoff_ts:
            old_files.append(f)

    return sorted(old_files)


def cleanup(days: int = 7, dry_run: bool = False) -> int:
    """Remove reports older than `days`. Returns count deleted."""
    old_files = find_old_reports(days)

    if not old_files:
        print(f"No reports older than {days} days found.")
        return 0

    print(f"Found {len(old_files)} report(s) older than {days} days:")
    for f in old_files:
        age_days = (
            datetime.now(timezone.utc)
            - datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        ).days
        print(f"  {f.name}  ({age_days}d old)")

    if dry_run:
        print("\n[dry-run] No files deleted.")
        return 0

    deleted = 0
    for f in old_files:
        try:
            f.unlink()
            deleted += 1
        except OSError as e:
            print(f"  WARNING: Failed to delete {f.name}: {e}", file=sys.stderr)

    print(f"\nDeleted {deleted}/{len(old_files)} report(s).")
    return deleted


def main():
    parser = argparse.ArgumentParser(description="Cleanup old eval reports")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Delete reports older than N days (default: 7)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List files without deleting"
    )
    args = parser.parse_args()

    cleanup(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
