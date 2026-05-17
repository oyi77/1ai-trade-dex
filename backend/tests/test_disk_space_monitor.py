"""Tests for G-04: Disk space monitoring in AGI health check."""
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from backend.core.agi_health_check import AGIHealthChecker, agi_health_checker


@pytest.fixture
def checker():
    return AGIHealthChecker()


class TestDiskSpaceCheck:
    def test_healthy_when_below_threshold(self, checker):
        fake_usage = SimpleNamespace(used=50 * (1024**3), total=100 * (1024**3), free=50 * (1024**3))
        with patch("shutil.disk_usage", return_value=fake_usage):
            with patch("backend.core.agi_health_check.settings", SimpleNamespace(
                DATABASE_URL="sqlite:///test.db",
                DISK_SPACE_WARN_PCT=90.0,
                DISK_SPACE_MAX_DB_SIZE_MB=5000.0,
            )):
                with patch("backend.config.ROOT_DIR", "/tmp"):
                    with patch("os.path.exists", return_value=False):
                        result = checker._check_disk_space()
        assert result["healthy"] is True
        assert result["used_pct"] == 50.0

    def test_unhealthy_when_above_threshold(self, checker):
        fake_usage = SimpleNamespace(used=95 * (1024**3), total=100 * (1024**3), free=5 * (1024**3))
        with patch("shutil.disk_usage", return_value=fake_usage):
            with patch("backend.core.agi_health_check.settings", SimpleNamespace(
                DATABASE_URL="sqlite:///test.db",
                DISK_SPACE_WARN_PCT=90.0,
                DISK_SPACE_MAX_DB_SIZE_MB=5000.0,
            )):
                with patch("backend.config.ROOT_DIR", "/tmp"):
                    with patch("os.path.exists", return_value=False):
                        result = checker._check_disk_space()
        assert result["healthy"] is False
        assert result["used_pct"] == 95.0

    def test_db_oversized(self, checker):
        fake_usage = SimpleNamespace(used=50 * (1024**3), total=100 * (1024**3), free=50 * (1024**3))
        with patch("shutil.disk_usage", return_value=fake_usage):
            with patch("backend.core.agi_health_check.settings", SimpleNamespace(
                DATABASE_URL="sqlite:///test.db",
                DISK_SPACE_WARN_PCT=90.0,
                DISK_SPACE_MAX_DB_SIZE_MB=100.0,
            )):
                with patch("backend.config.ROOT_DIR", "/tmp"):
                    with patch("os.path.exists", return_value=True):
                        with patch("os.path.getsize", return_value=200 * 1024 * 1024):  # 200 MB
                            result = checker._check_disk_space()
        assert result["healthy"] is False
        assert result.get("db_oversized") is True

    def test_postgres_no_db_size_check(self, checker):
        fake_usage = SimpleNamespace(used=50 * (1024**3), total=100 * (1024**3), free=50 * (1024**3))
        with patch("shutil.disk_usage", return_value=fake_usage):
            with patch("backend.core.agi_health_check.settings", SimpleNamespace(
                DATABASE_URL="postgresql://localhost/db",
                DISK_SPACE_WARN_PCT=90.0,
            )):
                with patch("backend.config.ROOT_DIR", "/tmp"):
                    result = checker._check_disk_space()
        assert result["healthy"] is True
        assert "db_size_mb" not in result

    def test_error_returns_unhealthy(self, checker):
        with patch("shutil.disk_usage", side_effect=OSError("permission denied")):
            with patch("backend.config.ROOT_DIR", "/nonexistent"):
                result = checker._check_disk_space()
        assert result["healthy"] is False
        assert "error" in result


class TestDiskSpaceInRunChecks:
    def test_disk_space_included_in_results(self, checker):
        with patch.object(checker, "_check_strategies", return_value={"healthy": True}):
            with patch.object(checker, "_check_data_freshness", return_value={"healthy": True}):
                with patch.object(checker, "_check_budget", return_value={"healthy": True}):
                    with patch.object(checker, "_check_scheduler", return_value={"healthy": True}):
                        with patch.object(checker, "_check_orphaned_positions", return_value={"healthy": True}):
                            with patch.object(checker, "_check_disk_space", return_value={"healthy": True, "used_pct": 50.0}):
                                result = checker.run_checks(db=MagicMock())
        assert "disk_space" in result
        assert result["disk_space"]["healthy"] is True
