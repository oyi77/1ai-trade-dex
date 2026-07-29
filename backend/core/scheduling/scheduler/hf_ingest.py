"""HF dataset ingestion job — extracted from _scheduler_core.py."""

from loguru import logger


def hf_ingest_weekly_job():
    """Wrapper for weekly HF dataset ingestion job."""
    try:
        from backend.scripts.ingest_hf_dataset import ingest_dataset

        path = ingest_dataset()
        logger.info("Weekly HF dataset ingestion complete: %s", path)
    except Exception as e:
        logger.warning("Weekly HF dataset ingestion failed: %s", e)