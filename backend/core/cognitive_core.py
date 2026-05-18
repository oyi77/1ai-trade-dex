"""CognitiveCoreAdapter — single interface to 1ai-hub brain.

Provides an ABC (CognitiveCoreAdapter) with three concrete implementations:
- OneAIHubCore  — production HTTP client to 1ai-hub API
- DegradedCore  — amnesia mode (returns defaults, logs warnings)
- MockCore       — in-memory dict storage for unit tests

See docs/architecture/adr-009-cognitive-core-interface.md for design decisions.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from backend.monitoring.agi_metrics import (
    record_cognitive_core_latency,
    record_cognitive_core_recall_stats,
    set_cognitive_core_health,
)


# ---------------------------------------------------------------------------
# Health status model
# ---------------------------------------------------------------------------

@dataclass
class CoreHealth:
    """Health status returned by health_check()."""
    status: str  # "online" | "amnesia" | "offline"
    latency_ms: float = 0.0
    last_success: Optional[str] = None
    queued_writes: int = 0


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class CognitiveCoreAdapter(ABC):
    """Abstract interface to a cognitive core (brain).

    All modules that store or retrieve knowledge route through this adapter.
    """

    @abstractmethod
    def remember(
        self,
        namespace: str,
        key: str,
        value: Any,
        importance: float = 0.5,
    ) -> None:
        """Store a memory in the given namespace."""

    @abstractmethod
    def recall(
        self,
        query: str,
        namespace: str = "default",
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Retrieve memories matching *query* in *namespace*."""

    @abstractmethod
    def forget(self, namespace: str, key: str) -> bool:
        """Delete a memory. Returns True if something was deleted."""

    @abstractmethod
    def health_check(self) -> CoreHealth:
        """Return current core health status."""

    @abstractmethod
    def get_personality(self) -> dict[str, Any]:
        """Return the active personality/mode configuration."""

    # Optional richer operations with default no-op / stub implementations
    # so that consuming modules can call them without guarding.

    def reason(
        self,
        context: str,
        question: str,
        personality_mode: str = "balanced",
    ) -> str:
        """Request reasoning from the core. Default returns empty string."""
        return ""

    def route_llm(
        self,
        prompt: str,
        task_type: str = "general",
        max_cost_usd: float = 0.05,
    ) -> str:
        """Route an LLM call through the core. Default returns empty string."""
        return ""

    def memory_stats(self) -> dict[str, Any]:
        """Return memory store statistics. Default returns empty dict."""
        return {}


# ---------------------------------------------------------------------------
# MockCore — in-memory implementation for tests
# ---------------------------------------------------------------------------

class MockCore(CognitiveCoreAdapter):
    """In-memory cognitive core for unit testing.

    Stores everything in a plain dict; no persistence, no external calls.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, tuple[Any, float]]] = {}
        self._personality: dict[str, Any] = {
            "mode": "balanced",
            "risk_tolerance": 0.5,
            "learning_rate": 0.1,
        }
        self._healthy = True
        self._call_log: list[tuple[str, dict[str, Any]]] = []

    # -- Core interface -------------------------------------------------------

    def remember(
        self,
        namespace: str,
        key: str,
        value: Any,
        importance: float = 0.5,
    ) -> None:
        self._call_log.append(("remember", {"namespace": namespace, "key": key}))
        t0 = time.monotonic()
        ns = self._store.setdefault(namespace, {})
        ns[key] = (value, importance)
        record_cognitive_core_latency("remember", time.monotonic() - t0)
        total = sum(len(n) for n in self._store.values())
        record_cognitive_core_recall_stats(1.0 if total > 0 else 0.0, total)

    def recall(
        self,
        query: str,
        namespace: str = "default",
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> list[dict[str, Any]]:
        self._call_log.append(("recall", {"namespace": namespace, "query": query}))
        t0 = time.monotonic()
        ns = self._store.get(namespace, {})
        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        for key, (value, importance) in ns.items():
            if importance < min_relevance:
                continue
            # Simple substring match for testing
            key_match = query_lower in key.lower()
            value_match = isinstance(value, str) and query_lower in value.lower()
            if key_match or value_match or not query:
                results.append({
                    "key": key,
                    "value": value,
                    "importance": importance,
                    "relevance": importance,
                })
                if len(results) >= limit:
                    break
        elapsed = time.monotonic() - t0
        record_cognitive_core_latency("recall", elapsed)
        hit_rate = len(results) / max(1, len(ns))
        total = sum(len(n) for n in self._store.values())
        record_cognitive_core_recall_stats(hit_rate, total)
        return results

    def forget(self, namespace: str, key: str) -> bool:
        self._call_log.append(("forget", {"namespace": namespace, "key": key}))
        t0 = time.monotonic()
        ns = self._store.get(namespace, {})
        if key in ns:
            del ns[key]
            record_cognitive_core_latency("forget", time.monotonic() - t0)
            return True
        record_cognitive_core_latency("forget", time.monotonic() - t0)
        return False

    def health_check(self) -> CoreHealth:
        sum(len(ns) for ns in self._store.values())
        status = "online" if self._healthy else "offline"
        set_cognitive_core_health(status)
        return CoreHealth(
            status=status,
            latency_ms=0.0,
            last_success=datetime.now(timezone.utc).isoformat(),
            queued_writes=0,
        )

    def get_personality(self) -> dict[str, Any]:
        return dict(self._personality)

    def reason(
        self,
        context: str,
        question: str,
        personality_mode: str = "balanced",
    ) -> str:
        self._call_log.append(("reason", {"question": question}))
        return f"[mock] Answer to: {question}"

    def route_llm(
        self,
        prompt: str,
        task_type: str = "general",
        max_cost_usd: float = 0.05,
    ) -> str:
        self._call_log.append(("route_llm", {"task_type": task_type}))
        return f"[mock] LLM response for: {task_type}"

    def memory_stats(self) -> dict[str, Any]:
        namespaces = {name: len(ns) for name, ns in self._store.items()}
        return {
            "total_memories": sum(namespaces.values()),
            "namespaces": namespaces,
        }

    # -- Test helpers ---------------------------------------------------------

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = healthy

    def set_personality(self, personality: dict[str, Any]) -> None:
        self._personality = personality

    @property
    def call_log(self) -> list[tuple[str, dict[str, Any]]]:
        return list(self._call_log)


# ---------------------------------------------------------------------------
# DegradedCore — amnesia mode fallback
# ---------------------------------------------------------------------------

class DegradedCore(CognitiveCoreAdapter):
    """Fallback cognitive core when 1ai-hub is unreachable.

    Returns empty/default values for all operations, logs degradation warnings.
    Buffers write operations in a local queue for replay on reconnection.
    """

    _MAX_QUEUE_SIZE = 10_000

    def __init__(self) -> None:
        self._write_queue: list[dict[str, Any]] = []
        self._last_success: Optional[str] = None
        self._started_at = datetime.now(timezone.utc)

    def remember(
        self,
        namespace: str,
        key: str,
        value: Any,
        importance: float = 0.5,
    ) -> None:
        t0 = time.monotonic()
        logger.warning(
            "[DegradedCore] remember() queued — amnesia mode (ns={}, key={})",
            namespace, key,
        )
        if len(self._write_queue) >= self._MAX_QUEUE_SIZE:
            dropped = self._write_queue.pop(0)
            logger.warning(
                "[DegradedCore] Write queue overflow — dropped oldest entry: {}",
                dropped.get("key"),
            )
        self._write_queue.append({
            "operation": "remember",
            "namespace": namespace,
            "key": key,
            "value": value,
            "importance": importance,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        record_cognitive_core_latency("remember", time.monotonic() - t0)

    def recall(
        self,
        query: str,
        namespace: str = "default",
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        logger.warning(
            "[DegradedCore] recall() returning empty — amnesia mode (query={})",
            query,
        )
        record_cognitive_core_latency("recall", time.monotonic() - t0)
        return []

    def forget(self, namespace: str, key: str) -> bool:
        t0 = time.monotonic()
        logger.warning(
            "[DegradedCore] forget() queued — amnesia mode (ns={}, key={})",
            namespace, key,
        )
        self._write_queue.append({
            "operation": "forget",
            "namespace": namespace,
            "key": key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        record_cognitive_core_latency("forget", time.monotonic() - t0)
        return False

    def health_check(self) -> CoreHealth:
        set_cognitive_core_health("amnesia")
        return CoreHealth(
            status="amnesia",
            latency_ms=0.0,
            last_success=self._last_success,
            queued_writes=len(self._write_queue),
        )

    def get_personality(self) -> dict[str, Any]:
        logger.warning("[DegradedCore] get_personality() returning default — amnesia mode")
        return {
            "mode": "degraded",
            "risk_tolerance": 0.3,
            "learning_rate": 0.0,
        }

    def reason(
        self,
        context: str,
        question: str,
        personality_mode: str = "balanced",
    ) -> str:
        logger.warning("[DegradedCore] reason() unavailable — amnesia mode")
        return ""

    def route_llm(
        self,
        prompt: str,
        task_type: str = "general",
        max_cost_usd: float = 0.05,
    ) -> str:
        logger.warning("[DegradedCore] route_llm() unavailable — amnesia mode")
        return ""

    def memory_stats(self) -> dict[str, Any]:
        return {
            "status": "amnesia",
            "queued_writes": len(self._write_queue),
        }

    def replay_queue(self, target: CognitiveCoreAdapter) -> int:
        """Replay queued writes into *target*. Returns number replayed."""
        count = 0
        while self._write_queue:
            op = self._write_queue.pop(0)
            try:
                if op["operation"] == "remember":
                    target.remember(
                        op["namespace"], op["key"], op["value"],
                        op.get("importance", 0.5),
                    )
                elif op["operation"] == "forget":
                    target.forget(op["namespace"], op["key"])
                count += 1
            except Exception as e:
                logger.error(
                    "[DegradedCore] Replay failed for op={}: {}",
                    op.get("operation"), e,
                )
                # Re-queue the failed op at the front
                self._write_queue.insert(0, op)
                break
        if count:
            self._last_success = datetime.now(timezone.utc).isoformat()
            logger.info("[DegradedCore] Replayed {} queued operations", count)
        return count


# ---------------------------------------------------------------------------
# OneAIHubCore — production implementation
# ---------------------------------------------------------------------------

class OneAIHubCore(CognitiveCoreAdapter):
    """Production cognitive core backed by the 1ai-hub HTTP API.

    Requires the ``httpx`` package. Falls back to DegradedCore on connection
    failure (handled by the caller / startup logic, not internally).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8200",
        api_key: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._last_success: Optional[str] = None
        self._last_latency_ms: float = 0.0
        self._client: Any = None  # lazy httpx.Client

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.Client(
                base_url=self._base_url,
                headers=headers,
                timeout=self._timeout,
            )
        return self._client

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """HTTP request with timing."""
        start = time.monotonic()
        try:
            client = self._get_client()
            resp = client.request(method, path, **kwargs)
            resp.raise_for_status()
            elapsed = (time.monotonic() - start) * 1000
            self._last_latency_ms = elapsed
            self._last_success = datetime.now(timezone.utc).isoformat()
            return resp.json()
        except Exception as e:
            self._last_latency_ms = (time.monotonic() - start) * 1000
            logger.error("[OneAIHubCore] {} {} failed: {}", method, path, e)
            raise

    def remember(
        self,
        namespace: str,
        key: str,
        value: Any,
        importance: float = 0.5,
    ) -> None:
        t0 = time.monotonic()
        self._request("POST", "/api/v1/memory", json={
            "namespace": namespace,
            "key": key,
            "value": value,
            "importance": importance,
        })
        record_cognitive_core_latency("remember", time.monotonic() - t0)

    def recall(
        self,
        query: str,
        namespace: str = "default",
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        data = self._request("GET", "/api/v1/memory/recall", params={
            "query": query,
            "namespace": namespace,
            "limit": limit,
            "min_relevance": min_relevance,
        })
        record_cognitive_core_latency("recall", time.monotonic() - t0)
        return data.get("results", [])

    def forget(self, namespace: str, key: str) -> bool:
        t0 = time.monotonic()
        try:
            self._request("DELETE", f"/api/v1/memory/{namespace}/{key}")
            record_cognitive_core_latency("forget", time.monotonic() - t0)
            return True
        except Exception:
            record_cognitive_core_latency("forget", time.monotonic() - t0)
            return False

    def health_check(self) -> CoreHealth:
        try:
            data = self._request("GET", "/api/v1/health")
            status = data.get("status", "online")
            set_cognitive_core_health(status)
            return CoreHealth(
                status=status,
                latency_ms=self._last_latency_ms,
                last_success=self._last_success,
                queued_writes=data.get("queued_writes", 0),
            )
        except Exception:
            set_cognitive_core_health("offline")
            return CoreHealth(
                status="offline",
                latency_ms=self._last_latency_ms,
                last_success=self._last_success,
            )

    def get_personality(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/personality")
        except Exception:
            return {"mode": "unknown", "risk_tolerance": 0.5, "learning_rate": 0.1}

    def reason(
        self,
        context: str,
        question: str,
        personality_mode: str = "balanced",
    ) -> str:
        data = self._request("POST", "/api/v1/reason", json={
            "context": context,
            "question": question,
            "personality_mode": personality_mode,
        })
        return data.get("answer", "")

    def route_llm(
        self,
        prompt: str,
        task_type: str = "general",
        max_cost_usd: float = 0.05,
    ) -> str:
        data = self._request("POST", "/api/v1/llm/route", json={
            "prompt": prompt,
            "task_type": task_type,
            "max_cost_usd": max_cost_usd,
        })
        return data.get("response", "")

    def memory_stats(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/memory/stats")
        except Exception:
            return {"status": "unavailable"}


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def create_cognitive_core(
    hub_url: str = "",
    hub_api_key: str = "",
) -> CognitiveCoreAdapter:
    """Create the best available cognitive core.

    Attempts OneAIHubCore if a hub URL is configured; returns DegradedCore otherwise.
    """
    if hub_url:
        try:
            core = OneAIHubCore(base_url=hub_url, api_key=hub_api_key)
            h = core.health_check()
            if h.status == "offline":
                raise ConnectionError("1ai-hub reported offline")
            logger.info("[CognitiveCore] Connected to 1ai-hub at {}", hub_url)
            return core
        except Exception as e:
            logger.warning(
                "[CognitiveCore] Failed to connect to 1ai-hub ({}): {} — using DegradedCore",
                hub_url, e,
            )
    else:
        logger.info("[CognitiveCore] No hub URL configured — using DegradedCore")
    return DegradedCore()
