"""Tests for HuggingFace Dataset Collector."""
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.data.hf_dataset_collector import (
    HFDatasetCollector,
    get_hf_collector,
    hf_dataset_collection_job,
)


class TestHFDatasetCollector:
    def setup_method(self):
        self.collector = HFDatasetCollector(cache_dir=Path("/tmp/test_hf_cache"))

    def teardown_method(self):
        import shutil
        cache = Path("/tmp/test_hf_cache")
        if cache.exists():
            shutil.rmtree(cache)

    def test_cache_key_deterministic(self):
        k1 = HFDatasetCollector._cache_key("repo/ds", "data.parquet", "train")
        k2 = HFDatasetCollector._cache_key("repo/ds", "data.parquet", "train")
        assert k1 == k2
        assert len(k1) == 16

    def test_cache_key_differs_for_different_inputs(self):
        k1 = HFDatasetCollector._cache_key("repo/a", "data.parquet", "train")
        k2 = HFDatasetCollector._cache_key("repo/b", "data.parquet", "train")
        assert k1 != k2

    def test_cache_valid_returns_false_when_missing(self):
        assert self.collector._cache_valid(Path("/nonexistent/file")) is False

    def test_cache_valid_returns_true_when_fresh(self, tmp_path):
        p = tmp_path / "fresh.parquet"
        p.write_text("data")
        assert self.collector._cache_valid(p) is True

    def test_cache_valid_returns_false_when_stale(self, tmp_path):
        p = tmp_path / "stale.parquet"
        p.write_text("data")
        old_time = time.time() - 100 * 3600
        import os
        os.utime(p, (old_time, old_time))
        assert self.collector._cache_valid(p) is False

    def test_list_cached_empty(self):
        assert self.collector.list_cached() == []

    def test_clear_cache_empty(self):
        assert self.collector.clear_cache() == 0

    def test_checksum_deterministic(self, tmp_path):
        p = tmp_path / "test.bin"
        p.write_bytes(b"hello world")
        c1 = HFDatasetCollector._checksum(p)
        c2 = HFDatasetCollector._checksum(p)
        assert c1 == c2
        assert len(c1) == 16

    @patch("backend.data.hf_dataset_collector.HFDatasetCollector._download")
    def test_fetch_caches_result(self, mock_download, tmp_path):
        import pandas as pd
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        mock_download.return_value = df

        self.collector.cache_dir = tmp_path
        result = self.collector.fetch("test/repo", "data.parquet")

        assert len(result) == 3
        assert mock_download.call_count == 1

        # Second call should use cache
        result2 = self.collector.fetch("test/repo", "data.parquet")
        assert len(result2) == 3
        assert mock_download.call_count == 1  # not called again

    @patch("backend.data.hf_dataset_collector.HFDatasetCollector._download")
    def test_fetch_force_refresh(self, mock_download, tmp_path):
        import pandas as pd
        df = pd.DataFrame({"x": [1]})
        mock_download.return_value = df

        self.collector.cache_dir = tmp_path
        self.collector.fetch("test/repo", "data.parquet")
        self.collector.fetch("test/repo", "data.parquet", force_refresh=True)

        assert mock_download.call_count == 2

    @patch("backend.data.hf_dataset_collector.HFDatasetCollector._download")
    def test_list_cached_after_fetch(self, mock_download, tmp_path):
        import pandas as pd
        df = pd.DataFrame({"x": [1, 2]})
        mock_download.return_value = df

        self.collector.cache_dir = tmp_path
        self.collector.fetch("test/repo", "data.parquet")

        cached = self.collector.list_cached()
        assert len(cached) == 1
        assert cached[0].rows == 2


class TestGetHFCollector:
    def test_singleton(self):
        import backend.data.hf_dataset_collector as mod
        mod._collector = None
        c1 = get_hf_collector()
        c2 = get_hf_collector()
        assert c1 is c2


@pytest.mark.asyncio
async def test_hf_dataset_collection_job_no_config():
    with patch("backend.data.hf_dataset_collector.settings", create=True) as mock_s:
        mock_s.HF_DATASET_REPOS = []
        # Should not raise
        await hf_dataset_collection_job()
