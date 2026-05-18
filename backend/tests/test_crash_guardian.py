"""Tests for crash_guardian.py -- G-01: auto-restart on crash."""
import asyncio
from unittest.mock import patch
import pytest

from backend.core.crash_guardian import CrashGuardian, ProcessHealth


@pytest.fixture
def guardian():
    g = CrashGuardian(check_interval=0.1, memory_restart_mb=100, max_unhealthy_checks=2)
    return g


def _make_pm2_output(name="polyedge-bot", status="online", restarts=0, memory=50*1024*1024, cpu=5.0):
    return [{
        "name": name,
        "pid": 12345,
        "pm2_env": {"status": status, "restart_time": restarts},
        "monit": {"memory": memory, "cpu": cpu},
    }]


class TestProcessHealth:
    def test_defaults(self):
        h = ProcessHealth(name="test")
        assert h.status == "unknown"
        assert h.restart_count == 0
        assert h.unhealthy_streak == 0

    def test_crash_guardian_defaults(self):
        g = CrashGuardian()
        assert g._running is False
        assert g._processes == {}


class TestGetProcessHealth:
    @pytest.mark.asyncio
    async def test_returns_health_for_known_process(self, guardian):
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=_make_pm2_output()):
            h = await guardian._get_process_health("polyedge-bot")
            assert h is not None
            assert h.name == "polyedge-bot"
            assert h.status == "online"
            assert h.pid == 12345

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_process(self, guardian):
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=_make_pm2_output(name="other")):
            h = await guardian._get_process_health("polyedge-bot")
            assert h is None

    @pytest.mark.asyncio
    async def test_returns_none_on_pm2_failure(self, guardian):
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=None):
            h = await guardian._get_process_health("polyedge-bot")
            assert h is None


class TestMemoryDetection:
    @pytest.mark.asyncio
    async def test_memory_exceeded_increments_streak(self, guardian):
        high_mem = _make_pm2_output(memory=200 * 1024 * 1024)  # 200 MB > 100 threshold
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=high_mem):
            with patch.object(guardian, "_restart_process") as mock_restart:
                await guardian._check_all_processes()
                assert guardian._processes["polyedge-bot"].unhealthy_streak == 1
                mock_restart.assert_not_called()  # streak not yet at max

    @pytest.mark.asyncio
    async def test_memory_triggers_restart_after_max_streak(self, guardian):
        high_mem = _make_pm2_output(memory=200 * 1024 * 1024)
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=high_mem):
            with patch.object(guardian, "_restart_process") as mock_restart:
                await guardian._check_all_processes()
                await guardian._check_all_processes()  # streak hits 2 == max_unhealthy_checks
                mock_restart.assert_called_once()
                assert "memory_leak" in str(mock_restart.call_args)


class TestCrashDetection:
    @pytest.mark.asyncio
    async def test_errored_status_increments_streak(self, guardian):
        crashed = _make_pm2_output(status="errored")
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=crashed):
            with patch.object(guardian, "_restart_process") as mock_restart:
                await guardian._check_all_processes()
                assert guardian._processes["polyedge-bot"].unhealthy_streak == 1
                mock_restart.assert_not_called()

    @pytest.mark.asyncio
    async def test_stopped_triggers_restart_after_max_streak(self, guardian):
        stopped = _make_pm2_output(status="stopped")
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=stopped):
            with patch.object(guardian, "_restart_process") as mock_restart:
                await guardian._check_all_processes()
                await guardian._check_all_processes()
                mock_restart.assert_called_once()
                assert "status_stopped" in str(mock_restart.call_args)


class TestRestartDetection:
    @pytest.mark.asyncio
    async def test_detects_restart_count_increase(self, guardian):
        initial = _make_pm2_output(restarts=3)
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=initial):
            await guardian._check_all_processes()
            assert guardian._processes["polyedge-bot"].restart_count == 3

        bumped = _make_pm2_output(restarts=5)
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=bumped):
            await guardian._check_all_processes()
            assert guardian._processes["polyedge-bot"].restart_count == 5


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self, guardian):
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=_make_pm2_output()):
            guardian.start()
            assert guardian._running is True
            await asyncio.sleep(0.2)
            await guardian.stop()
            assert guardian._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self, guardian):
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=_make_pm2_output()):
            guardian.start()
            guardian.start()  # should not create duplicate task
            await asyncio.sleep(0.1)
            await guardian.stop()


class TestStatus:
    def test_status_empty_before_check(self, guardian):
        assert guardian.status == {}

    @pytest.mark.asyncio
    async def test_status_after_check(self, guardian):
        with patch.object(CrashGuardian, "_pm2_jlist", return_value=_make_pm2_output()):
            await guardian._check_all_processes()
            s = guardian.status
            assert "polyedge-bot" in s
            assert s["polyedge-bot"]["status"] == "online"
