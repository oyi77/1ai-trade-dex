"""Tests for CognitiveCoreAdapter — MockCore round-trip, DegradedCore, ABC contract."""
from __future__ import annotations

import pytest
from backend.core.cognitive_core import (
    CognitiveCoreAdapter,
    CoreHealth,
    DegradedCore,
    MockCore,
    create_cognitive_core,
)


# ---------------------------------------------------------------------------
# MockCore round-trip tests
# ---------------------------------------------------------------------------

class TestMockCoreRememberRecall:
    def test_remember_and_recall_basic(self):
        core = MockCore()
        core.remember("trades", "trade_001", {"pnl": 42.0})
        results = core.recall("trade_001", namespace="trades")
        assert len(results) == 1
        assert results[0]["key"] == "trade_001"
        assert results[0]["value"] == {"pnl": 42.0}

    def test_recall_empty_namespace(self):
        core = MockCore()
        results = core.recall("anything", namespace="nonexistent")
        assert results == []

    def test_recall_respects_limit(self):
        core = MockCore()
        for i in range(20):
            core.remember("ns", f"key_{i:03d}", f"val_{i}")
        results = core.recall("", namespace="ns", limit=5)
        assert len(results) <= 5

    def test_recall_min_relevance_filter(self):
        core = MockCore()
        core.remember("ns", "low", "v", importance=0.1)
        core.remember("ns", "high", "v", importance=0.9)
        results = core.recall("", namespace="ns", min_relevance=0.5)
        assert all(r["importance"] >= 0.5 for r in results)

    def test_remember_overwrites(self):
        core = MockCore()
        core.remember("ns", "k", "old")
        core.remember("ns", "k", "new")
        results = core.recall("k", namespace="ns")
        assert results[0]["value"] == "new"

    def test_recall_query_matches_value(self):
        core = MockCore()
        core.remember("lessons", "btc_crash", "Never go all-in during a crash")
        results = core.recall("crash", namespace="lessons")
        assert len(results) == 1


class TestMockCoreForget:
    def test_forget_existing(self):
        core = MockCore()
        core.remember("ns", "k", "v")
        assert core.forget("ns", "k") is True
        assert core.recall("k", namespace="ns") == []

    def test_forget_nonexistent(self):
        core = MockCore()
        assert core.forget("ns", "missing") is False


class TestMockCoreHealth:
    def test_health_online(self):
        core = MockCore()
        h = core.health_check()
        assert h.status == "online"
        assert h.queued_writes == 0

    def test_health_offline(self):
        core = MockCore()
        core.set_healthy(False)
        h = core.health_check()
        assert h.status == "offline"


class TestMockCorePersonality:
    def test_default_personality(self):
        core = MockCore()
        p = core.get_personality()
        assert p["mode"] == "balanced"
        assert 0.0 <= p["risk_tolerance"] <= 1.0

    def test_set_personality(self):
        core = MockCore()
        core.set_personality({"mode": "aggressive", "risk_tolerance": 0.9, "learning_rate": 0.5})
        p = core.get_personality()
        assert p["mode"] == "aggressive"


class TestMockCoreReasonAndRoute:
    def test_reason_returns_string(self):
        core = MockCore()
        result = core.reason("market is crashing", "should I sell?")
        assert isinstance(result, str)
        assert "should I sell?" in result

    def test_route_llm_returns_string(self):
        core = MockCore()
        result = core.route_llm("analyze BTC", task_type="analysis")
        assert isinstance(result, str)
        assert "analysis" in result


class TestMockCoreMemoryStats:
    def test_empty_stats(self):
        core = MockCore()
        stats = core.memory_stats()
        assert stats["total_memories"] == 0

    def test_populated_stats(self):
        core = MockCore()
        core.remember("a", "k1", "v1")
        core.remember("a", "k2", "v2")
        core.remember("b", "k3", "v3")
        stats = core.memory_stats()
        assert stats["total_memories"] == 3
        assert stats["namespaces"]["a"] == 2
        assert stats["namespaces"]["b"] == 1


class TestMockCoreCallLog:
    def test_call_log_tracks_operations(self):
        core = MockCore()
        core.remember("ns", "k", "v")
        core.recall("k", namespace="ns")
        core.forget("ns", "k")
        log = core.call_log
        assert len(log) == 3
        assert log[0][0] == "remember"
        assert log[1][0] == "recall"
        assert log[2][0] == "forget"


# ---------------------------------------------------------------------------
# DegradedCore tests
# ---------------------------------------------------------------------------

class TestDegradedCore:
    def test_health_is_amnesia(self):
        core = DegradedCore()
        h = core.health_check()
        assert h.status == "amnesia"

    def test_remember_queues(self):
        core = DegradedCore()
        core.remember("ns", "k", "v")
        assert len(core._write_queue) == 1

    def test_recall_returns_empty(self):
        core = DegradedCore()
        assert core.recall("anything") == []

    def test_forget_returns_false(self):
        core = DegradedCore()
        assert core.forget("ns", "k") is False

    def test_queue_overflow_drops_oldest(self):
        core = DegradedCore()
        for i in range(10_001):
            core.remember("ns", f"k{i}", f"v{i}")
        assert len(core._write_queue) == 10_000

    def test_replay_queue(self):
        degraded = DegradedCore()
        degraded.remember("ns", "k1", "v1")
        degraded.remember("ns", "k2", "v2")
        target = MockCore()
        count = degraded.replay_queue(target)
        assert count == 2
        assert len(degraded._write_queue) == 0
        results = target.recall("k1", namespace="ns")
        assert len(results) == 1

    def test_get_personality_returns_degraded(self):
        core = DegradedCore()
        p = core.get_personality()
        assert p["mode"] == "degraded"


# ---------------------------------------------------------------------------
# ABC contract tests
# ---------------------------------------------------------------------------

class TestABCContract:
    def test_mock_core_is_subclass(self):
        assert issubclass(MockCore, CognitiveCoreAdapter)

    def test_degraded_core_is_subclass(self):
        assert issubclass(DegradedCore, CognitiveCoreAdapter)

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            CognitiveCoreAdapter()


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

class TestCreateCognitiveCore:
    def test_no_url_returns_degraded(self):
        core = create_cognitive_core(hub_url="")
        assert isinstance(core, DegradedCore)

    def test_invalid_url_returns_degraded(self):
        core = create_cognitive_core(hub_url="http://localhost:1", hub_api_key="")
        assert isinstance(core, DegradedCore)


# ---------------------------------------------------------------------------
# CoreHealth dataclass
# ---------------------------------------------------------------------------

class TestCoreHealth:
    def test_defaults(self):
        h = CoreHealth(status="online")
        assert h.latency_ms == 0.0
        assert h.last_success is None
        assert h.queued_writes == 0

    def test_custom_values(self):
        h = CoreHealth(status="amnesia", latency_ms=42.5, queued_writes=7)
        assert h.status == "amnesia"
        assert h.latency_ms == 42.5
        assert h.queued_writes == 7
