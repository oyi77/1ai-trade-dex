"""Eval reports API — serves AGI evaluation reports from backend/evals/reports/."""

import json
import os
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["Evals"])

EVALS_REPORTS_DIR = Path(__file__).resolve().parent.parent / "evals" / "reports"


def _parse_report_timestamp(filename: str) -> str:
    """Parse timestamp from a report filename like agi_score_20260525_170247.json."""
    try:
        parts = filename.replace(".json", "").split("_")
        ts_part = parts[-1]  # "20260525_170247"
        dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
        return dt.isoformat()
    except (ValueError, IndexError):
        return ""


@router.get("/evals/reports")
async def list_eval_reports():
    """List all eval report files with metadata."""
    if not EVALS_REPORTS_DIR.exists():
        return {"reports": []}

    reports = []
    for f in sorted(EVALS_REPORTS_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if f.suffix != ".json":
            continue
        # Parse benchmark type from filename (before the timestamp)
        name_parts = f.stem.rsplit("_", 2)  # e.g. ["agi_score", "20260525", "170247"]
        benchmark_type = name_parts[0] if len(name_parts) >= 3 else f.stem
        timestamp = _parse_report_timestamp(f.name)

        # Read just the top-level fields for summary
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        reports.append({
            "filename": f.name,
            "benchmark_type": benchmark_type,
            "timestamp": timestamp or data.get("timestamp", ""),
            "score": data.get("score"),
            "passed": data.get("passed"),
            "certification_eligible": data.get("certification_eligible"),
            "passed_benchmarks": data.get("passed_benchmarks"),
            "failed_benchmarks": data.get("failed_benchmarks"),
        })

    return {"reports": reports}


@router.get("/evals/reports/{filename}")
async def get_eval_report(filename: str):
    """Return full content of a single eval report."""
    # Sanitize: prevent path traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = EVALS_REPORTS_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        with open(filepath) as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")
