"""HuggingFace Dataset Collector — download/cache datasets for ML training.

Fetches prediction-market and financial datasets from HuggingFace Hub,
caches them locally as Parquet, and provides a clean interface for the
training pipeline.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

CACHE_DIR = Path("data/hf_cache")


@dataclass
class DatasetMeta:
    """Metadata for a cached dataset."""

    repo_id: str
    filename: str
    local_path: Path
    downloaded_at: float
    size_bytes: int
    rows: int
    checksum: str


@dataclass
class HFDatasetCollector:
    """Download and cache HuggingFace datasets for ML training.

    Uses huggingface_hub to fetch datasets, stores them locally as Parquet
    for fast repeated reads. Supports TTL-based cache invalidation.
    """

    cache_dir: Path = CACHE_DIR
    cache_ttl_hours: float = 24.0
    _meta_cache: dict[str, DatasetMeta] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        repo_id: str,
        filename: str = "data.parquet",
        split: str = "train",
        force_refresh: bool = False,
    ) -> Any:
        """Fetch a dataset from HuggingFace Hub, returning a pandas DataFrame.

        Uses local cache when available and not expired.

        Args:
            repo_id: HuggingFace dataset repo (e.g. "username/dataset").
            filename: File within the repo to download.
            split: Dataset split (train/validation/test).
            force_refresh: Bypass cache and re-download.

        Returns:
            pandas DataFrame with the dataset contents.
        """
        import pandas as pd

        cache_key = self._cache_key(repo_id, filename, split)
        local_path = self.cache_dir / f"{cache_key}.parquet"

        if not force_refresh and self._cache_valid(local_path):
            logger.debug(f"HF cache hit: {repo_id}/{filename} ({split})")
            return pd.read_parquet(local_path)

        logger.info(f"HF downloading: {repo_id}/{filename} ({split})")
        df = self._download(repo_id, filename, split)

        if df is not None and not df.empty:
            df.to_parquet(local_path, index=False)
            self._meta_cache[cache_key] = DatasetMeta(
                repo_id=repo_id,
                filename=filename,
                local_path=local_path,
                downloaded_at=time.time(),
                size_bytes=local_path.stat().st_size,
                rows=len(df),
                checksum=self._checksum(local_path),
            )
            logger.info(f"HF cached {len(df)} rows -> {local_path}")

        return df

    def list_cached(self) -> list[DatasetMeta]:
        """List all cached datasets."""
        metas: list[DatasetMeta] = []
        for p in sorted(self.cache_dir.glob("*.parquet")):
            key = p.stem
            if key in self._meta_cache:
                metas.append(self._meta_cache[key])
            else:
                try:
                    import pyarrow.parquet as pq

                    rows = pq.read_metadata(p).num_rows
                except Exception:
                    rows = 0
                metas.append(
                    DatasetMeta(
                        repo_id="unknown",
                        filename=p.name,
                        local_path=p,
                        downloaded_at=p.stat().st_mtime,
                        size_bytes=p.stat().st_size,
                        rows=rows,
                        checksum=self._checksum(p),
                    )
                )
        return metas

    def clear_cache(self, older_than_hours: float | None = None) -> int:
        """Remove cached datasets. Returns count removed."""
        removed = 0
        cutoff = time.time() - (older_than_hours * 3600) if older_than_hours else 0
        for p in self.cache_dir.glob("*.parquet"):
            if older_than_hours is None or p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        if removed:
            logger.info(f"HF cache: removed {removed} files")
        return removed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download(self, repo_id: str, filename: str, split: str) -> Optional[Any]:
        """Download dataset from HuggingFace Hub."""
        try:
            from huggingface_hub import hf_hub_download
            import pandas as pd

            path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                repo_type="dataset",
            )
            if filename.endswith(".parquet"):
                return pd.read_parquet(path)
            elif filename.endswith(".csv"):
                return pd.read_csv(path)
            elif filename.endswith(".json") or filename.endswith(".jsonl"):
                return pd.read_json(path, lines=filename.endswith(".jsonl"))
            else:
                logger.warning(f"Unsupported file format: {filename}")
                return pd.read_parquet(path)
        except ImportError:
            logger.error(
                "huggingface_hub not installed — run: pip install huggingface_hub"
            )
            return None
        except Exception:
            logger.exception(f"Failed to download {repo_id}/{filename}")
            return None

    def _cache_valid(self, path: Path) -> bool:
        """Check if cached file exists and is within TTL."""
        if not path.exists():
            return False
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        return age_hours < self.cache_ttl_hours

    @staticmethod
    def _cache_key(repo_id: str, filename: str, split: str) -> str:
        """Generate a filesystem-safe cache key."""
        raw = f"{repo_id}::{filename}::{split}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _checksum(path: Path) -> str:
        """Compute SHA-256 checksum of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()[:16]


# Module-level singleton
_collector: Optional[HFDatasetCollector] = None


def get_hf_collector() -> HFDatasetCollector:
    """Get or create the module-level HFDatasetCollector singleton."""
    global _collector
    if _collector is None:
        _collector = HFDatasetCollector()
    return _collector


async def hf_dataset_collection_job() -> None:
    """Scheduler job: refresh configured HuggingFace datasets."""
    from backend.config import settings

    repos = getattr(settings, "HF_DATASET_REPOS", [])
    if not repos:
        logger.debug("HF_DATASET_REPOS not configured — skipping")
        return

    collector = get_hf_collector()
    for entry in repos:
        if isinstance(entry, str):
            repo_id, filename = entry, "data.parquet"
        elif isinstance(entry, dict):
            repo_id = entry.get("repo_id", "")
            filename = entry.get("filename", "data.parquet")
        else:
            continue
        try:
            df = collector.fetch(repo_id, filename)
            logger.info(
                f"HF collected {repo_id}: {len(df) if df is not None else 0} rows"
            )
        except Exception:
            logger.exception(f"HF collection failed for {repo_id}")
