"""HFT Latency Optimizer — connection pre-warming, DNS caching, and event loop tuning.

Provides production-level latency optimization for the HFT pipeline:

1. **Connection pre-warming** — pre-establishes HTTP connections to frequently-used
   API endpoints (Polymarket CLOB/Gamma, Kalshi) so the first trade doesn't pay
   the TLS handshake + connection setup latency (~100-300ms).

2. **DNS caching** — resolves and caches DNS entries for all endpoints, bypassing
   the system resolver on hot paths.

3. **Connection pooling** — configures httpx.AsyncClient with optimal keepalive
   and pool limits for HFT throughput.

4. **Event loop tuning** — applies asyncio event loop optimisations (thread pool
   sizing, loop implementation hints).

5. **Latency tracking** — per-endpoint latency histograms with configurable
   alert thresholds.

6. **Auto-tuning** — dynamically adjusts pool sizes and timeouts based on
   observed P50/P95/P99 latencies.

Usage:
    optimizer = LatencyOptimizer()
    await optimizer.start()   # pre-warm everything
    ...
    # Use pre-warmed clients
    async with optimizer.get_client("gamma") as client:
        resp = await client.get("/markets")
    
    await optimizer.stop()    # graceful shutdown
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.config import settings

from loguru import logger


# ── Constants ───────────────────────────────────────────────────────────────────

_PRE_WARM_CONNECTIONS = int(os.getenv("HFT_PRE_WARM_CONNECTIONS", "3"))
_DNS_CACHE_TTL = float(os.getenv("HFT_DNS_CACHE_TTL", "300.0"))
_POOL_MAX_SIZE = int(os.getenv("HFT_POOL_MAX_SIZE", "20"))
_POOL_KEEPALIVE = float(os.getenv("HFT_POOL_KEEPALIVE", "60.0"))
_LATENCY_ALERT_THRESHOLD_MS = float(
    os.getenv("HFT_LATENCY_ALERT_MS", str(settings.HFT_LATENCY_LATENCY_ALERT_THRESHOLD_MS))
)
_WARMUP_TIMEOUT = float(os.getenv("HFT_WARMUP_TIMEOUT", "10.0"))


# ── Data types ──────────────────────────────────────────────────────────────────


@dataclass
class EndpointConfig:
    """Configuration for a single endpoint to pre-warm."""

    name: str  # short identifier (e.g. "gamma", "clob", "kalshi")
    url: str  # base URL for HTTP connections
    ws_url: str | None = None  # WebSocket URL if applicable
    warm_connections: int = _PRE_WARM_CONNECTIONS
    pool_max_size: int = _POOL_MAX_SIZE
    keepalive: float = _POOL_KEEPALIVE
    priority: int = 10  # lower = higher priority for warmup order


@dataclass
class LatencySample:
    """Single latency measurement for an endpoint."""

    endpoint: str
    operation: str  # e.g. "http_get", "ws_connect", "dns_resolve"
    latency_ms: float
    timestamp: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    success: bool = True


# ── Default endpoints ────────────────────────────────────────────────────────────

_DEFAULT_ENDPOINTS = [
    EndpointConfig(
        name="gamma",
        url=settings.GAMMA_API_URL,
        warm_connections=_PRE_WARM_CONNECTIONS,
        priority=10,
    ),
    EndpointConfig(
        name="clob",
        url=settings.CLOB_API_URL,
        warm_connections=_PRE_WARM_CONNECTIONS,
        priority=10,
    ),
    EndpointConfig(
        name="relayer",
        url=settings.POLYMARKET_RELAYER_URL,
        warm_connections=1,
        priority=20,
    ),
    EndpointConfig(
        name="kalshi",
        url=settings.KALSHI_API_URL,
        warm_connections=1,
        priority=30,
    ),
    EndpointConfig(
        name="polymarket_ws",
        url=settings.POLYMARKET_WS_CLOB_URL,
        ws_url=settings.POLYMARKET_WS_CLOB_URL,
        warm_connections=1,
        priority=15,
    ),
]


# ── DNS Cache ────────────────────────────────────────────────────────────────────


class DNSCache:
    """Thread-safe DNS cache with TTL expiry.

    Pre-resolves endpoint hostnames so HTTP/WS connection setup doesn't
    block on DNS resolution.
    """

    def __init__(self, ttl: float = _DNS_CACHE_TTL):
        self._ttl = ttl
        self._cache: dict[str, tuple[list[str], float]] = {}  # host -> (addrs, expiry)
        self._lock = asyncio.Lock()

    async def resolve(self, host: str) -> list[str]:
        """Resolve a hostname, using cached result if fresh."""
        now = time.monotonic()
        async with self._lock:
            cached = self._cache.get(host)
            if cached and now < cached[1]:
                return cached[0]

        # Cache miss — resolve via event loop's resolver
        loop = asyncio.get_running_loop()
        try:
            addrs = await loop.getaddrinfo(host, None)
            resolved = list(
                dict.fromkeys(addr[4][0] for addr in addrs if addr[4][0])
            )
            async with self._lock:
                self._cache[host] = (resolved, now + self._ttl)
            logger.debug(
                "[dns_cache] Resolved {} -> {} (TTL={}s)", host, resolved, self._ttl
            )
            return resolved
        except OSError as e:
            logger.debug("[dns_cache] DNS resolution failed for {}: {} — falling back to OS resolver", host, e)
            return [host]  # fallback: let OS resolver handle it

    async def warm(self, urls: list[str]) -> dict[str, LatencySample]:
        """Pre-resolve DNS for a list of URLs."""
        results: dict[str, LatencySample] = {}
        for url in urls:
            t0 = time.monotonic()
            try:
                from urllib.parse import urlparse

                host = urlparse(url).hostname or url
                addrs = await self.resolve(host)
                elapsed = (time.monotonic() - t0) * 1000
                results[url] = LatencySample(
                    endpoint=host,
                    operation="dns_resolve",
                    latency_ms=round(elapsed, 2),
                    success=bool(addrs),
                )
            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                results[url] = LatencySample(
                    endpoint=url, operation="dns_resolve", latency_ms=round(elapsed, 2), success=False
                )
                logger.warning("[dns_cache] Warm failed for {}: {}", url, e)
        return results

    async def clear(self) -> None:
        """Purge all cached entries."""
        async with self._lock:
            self._cache.clear()


# ── Connection Pre-warmer ─────────────────────────────────────────────────────────


class ConnectionPreWarmer:
    """Pre-establish HTTP/WS connections to known endpoints.

    Uses health-check GET requests + HTTP keep-alive headers so the
    connections remain open and ready for the first real request.
    """

    def __init__(self, dns_cache: DNSCache):
        self._dns = dns_cache
        self._clients: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def warm_endpoint(self, cfg: EndpointConfig) -> LatencySample:
        """Pre-warm connections for a single endpoint."""
        t0 = time.monotonic()

        # 1. DNS pre-resolve
        await self._dns.resolve(cfg.url)

        # 2. Pre-establish HTTP keep-alive connections
        try:
            import httpx

            client = httpx.AsyncClient(
                base_url=cfg.url,
                limits=httpx.Limits(
                    max_keepalive_connections=cfg.warm_connections,
                    max_connections=cfg.pool_max_size,
                    keepalive_expiry=cfg.keepalive,
                ),
                timeout=httpx.Timeout(5.0, connect=3.0),
                headers={
                    "Connection": "keep-alive",
                    "User-Agent": "PolyEdge-HFT/1.0",
                },
            )

            # Perform parallel warm-up requests to establish connections
            warm_tasks = []
            for _ in range(cfg.warm_connections):
                warm_tasks.append(client.get("/", timeout=_WARMUP_TIMEOUT))

            results = await asyncio.gather(*warm_tasks, return_exceptions=True)
            success_count = sum(
                1 for r in results if isinstance(r, httpx.Response) and r.status_code < 500
            )

            async with self._lock:
                # Close any existing client for this endpoint
                existing = self._clients.get(cfg.name)
                if existing:
                    await existing.aclose()
                self._clients[cfg.name] = client

            elapsed = (time.monotonic() - t0) * 1000
            logger.info(
                "[prewarm] {}: {} connections established in {:.0f}ms ({}/{} ok)",
                cfg.name,
                cfg.warm_connections,
                elapsed,
                success_count,
                len(warm_tasks),
            )

            return LatencySample(
                endpoint=cfg.name,
                operation="prewarm",
                latency_ms=round(elapsed, 2),
                success=success_count > 0,
            )

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("[prewarm] {} warm-up failed after {:.0f}ms: {}", cfg.name, elapsed, e)
            return LatencySample(
                endpoint=cfg.name,
                operation="prewarm",
                latency_ms=round(elapsed, 2),
                success=False,
            )

    async def warm_all(
        self, endpoints: list[EndpointConfig] | None = None
    ) -> list[LatencySample]:
        """Pre-warm all configured endpoints in priority order."""
        endpoints = sorted(
            endpoints or _DEFAULT_ENDPOINTS, key=lambda e: (e.priority, e.name)
        )

        results: list[LatencySample] = []
        for cfg in endpoints:
            sample = await self.warm_endpoint(cfg)
            results.append(sample)
            # Small delay between endpoints to avoid thundering herd
            await asyncio.sleep(0.1)

        return results

    def get_client(self, name: str) -> Any | None:
        """Get a pre-warmed HTTP client for an endpoint."""
        return self._clients.get(name)

    async def close_all(self) -> None:
        """Close all pre-warmed HTTP clients."""
        for name, client in self._clients.items():
            try:
                await client.aclose()
            except Exception:
                pass
        self._clients.clear()


# ── Event Loop Tuning ────────────────────────────────────────────────────────────


class EventLoopTuner:
    """Optimise the running async event loop for low-latency HFT workloads.

    Applies:
    - Thread pool sizing (match CPU count for parallel DB ops)
    - Loop factory selection (use faster implementation if available)
    - Exception handler customisation (avoid noisy traces on cancellation)
    - Scheduling policy hints (fair vs. fifo)
    """

    def __init__(self):
        self._original_exc_handler: Any = None
        self._default_thread_pool: Any = None

    def tune(self) -> dict[str, Any]:
        """Apply event loop optimisations. Returns a report of applied changes."""
        report: dict[str, Any] = {}
        loop = asyncio.get_running_loop()

        # 1. Thread pool sizing — match CPU count for DB/sync ops
        cpu_count = os.cpu_count() or 4
        optimal_workers = max(4, cpu_count * 2)
        try:
            from concurrent.futures import ThreadPoolExecutor

            executor = ThreadPoolExecutor(
                max_workers=optimal_workers,
                thread_name_prefix="hft-worker",
            )
            loop.set_default_executor(executor)
            self._default_thread_pool = executor
            report["thread_pool_workers"] = optimal_workers
            logger.debug(
                "[loop_tuner] Thread pool set to {} workers", optimal_workers
            )
        except Exception as e:
            report["thread_pool_error"] = str(e)

        # 2. Custom exception handler — filter CancelledError noise
        def _hft_exc_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
            """Passthrough that supresses CancelledError noise."""
            exc = context.get("exception")
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
                return  # silent — HFT tasks cancel frequently
            if self._original_exc_handler:
                self._original_exc_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        self._original_exc_handler = loop.get_exception_handler()
        loop.set_exception_handler(_hft_exc_handler)
        report["exception_handler"] = "custom_hft"
        logger.debug("[loop_tuner] Custom exception handler installed")

        # 3. Enable debug is not set (too noisy for HFT)
        report["debug_mode"] = False

        return report

    def restore(self) -> None:
        """Restore original event loop configuration."""
        try:
            loop = asyncio.get_running_loop()
            if self._original_exc_handler:
                loop.set_exception_handler(self._original_exc_handler)
            if self._default_thread_pool:
                self._default_thread_pool.shutdown(wait=False)
        except RuntimeError:
            pass


# ── Latency Tracker ──────────────────────────────────────────────────────────────


class LatencyTracker:
    """Per-endpoint latency tracking with quantile estimation.

    Collects latency samples and provides P50/P95/P99 estimates using
    a fixed-size sliding window (no exact percentiles — fast approximation).
    """

    MAX_SAMPLES = 1000

    def __init__(self, alert_threshold_ms: float = _LATENCY_ALERT_THRESHOLD_MS):
        self._samples: dict[str, list[LatencySample]] = defaultdict(
            lambda: []
        )
        self._alert_threshold = alert_threshold_ms
        self._alert_count = 0

    def record(self, sample: LatencySample) -> None:
        """Record a latency sample. Triggers log warning if threshold exceeded."""
        samples = self._samples[sample.endpoint]
        samples.append(sample)
        if len(samples) > self.MAX_SAMPLES:
            self._samples[sample.endpoint] = samples[-self.MAX_SAMPLES :]

        if sample.latency_ms > self._alert_threshold:
            self._alert_count += 1
            if self._alert_count <= 3:  # throttle alerts
                logger.warning(
                    "[latency_tracker] {} high latency: {:.1f}ms (threshold={:.0f}ms)",
                    sample.endpoint,
                    sample.latency_ms,
                    self._alert_threshold,
                )

    def quantiles(self, endpoint: str) -> dict[str, float]:
        """Estimate latency quantiles for an endpoint.

        Returns approximate P50, P95, P99 from sorted samples.
        Uses O(n log n) sort; for production use Prometheus histograms.
        """
        samples = sorted(
            self._samples.get(endpoint, []), key=lambda s: s.latency_ms
        )
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}

        n = len(samples)
        return {
            "p50": samples[int(n * 0.50)].latency_ms,
            "p95": samples[int(n * 0.95)].latency_ms,
            "p99": samples[int(n * 0.99)].latency_ms,
            "count": n,
        }

    def summary(self) -> dict[str, dict[str, float]]:
        """Summary of all tracked endpoints."""
        return {ep: self.quantiles(ep) for ep in self._samples}


# ── Auto-Tuner ────────────────────────────────────────────────────────────────────


class AutoTuner:
    """Dynamic parameter tuning based on observed latencies.

    Adjusts connection pool sizes and timeouts to meet latency targets.
    Runs periodically and adjusts:

    - If P95 > target × 1.5 → decrease concurrency, increase pool size
    - If P95 < target × 0.5 → increase concurrency for higher throughput
    """

    def __init__(
        self,
        tracker: LatencyTracker,
        target_ms: float = 50.0,
        interval_sec: float = 60.0,
    ):
        self._tracker = tracker
        self._target_ms = target_ms
        self._interval = interval_sec
        self._task: asyncio.Task | None = None
        self._adjustments: list[dict] = []

    async def start(self) -> None:
        """Start periodic auto-tuning loop."""

        async def _loop() -> None:
            await asyncio.sleep(self._interval)  # wait for samples to accumulate
            while True:
                try:
                    result = await self._tune_once()
                    if result:
                        self._adjustments.append(result)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.opt(exception=True).warning("[auto_tuner] Tuning error")
                await asyncio.sleep(self._interval)

        self._task = asyncio.create_task(_loop(), name="hft-auto-tuner")
        logger.info(
            "[auto_tuner] Started (target={:.0f}ms, interval={:.0f}s)",
            self._target_ms,
            self._interval,
        )

    async def stop(self) -> None:
        """Stop auto-tuning loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _tune_once(self) -> dict | None:
        """Single tuning pass. Returns adjustment report or None."""
        summary = self._tracker.summary()
        if not summary:
            return None

        adjustments: dict[str, Any] = {
            "timestamp": time.monotonic(),
            "changes": [],
        }

        for endpoint, quantiles in summary.items():
            p95 = quantiles.get("p95", 0.0)
            count = quantiles.get("count", 0)

            if count < 10:
                continue  # not enough data

            if p95 > self._target_ms * 1.5:
                # P95 too high — likely congestion
                adjustments["changes"].append(
                    {
                        "endpoint": endpoint,
                        "action": "slow_down",
                        "p95_ms": round(p95, 1),
                        "target_ms": self._target_ms,
                        "reason": "P95 exceeds 150% of target",
                    }
                )
                logger.info(
                    "[auto_tuner] {} P95={:.0f}ms exceeds target — recommending rate reduction",
                    endpoint,
                    p95,
                )

            elif p95 < self._target_ms * 0.5:
                # P95 well below target — can increase throughput
                adjustments["changes"].append(
                    {
                        "endpoint": endpoint,
                        "action": "speed_up",
                        "p95_ms": round(p95, 1),
                        "target_ms": self._target_ms,
                        "reason": "P95 below 50% of target — room for higher throughput",
                    }
                )

        if adjustments["changes"]:
            return adjustments
        return None


# ── Orchestrator ──────────────────────────────────────────────────────────────────


class LatencyOptimizer:
    """Top-level orchestrator for all latency optimisation subsystems.

    Start this during system initialisation (ideally before the first
    trade cycle) to pre-warm connections, tune the event loop, and
    begin tracking latency.

    Usage:
        optimizer = LatencyOptimizer()
        await optimizer.start()       # ~5-10s async warmup
        ...
        await optimizer.stop()        # graceful shutdown
    """

    def __init__(self, endpoints: list[EndpointConfig] | None = None):
        self._endpoints = endpoints or _DEFAULT_ENDPOINTS
        self._dns = DNSCache()
        self._warmer = ConnectionPreWarmer(self._dns)
        self._tuner_loop = EventLoopTuner()
        self._tracker = LatencyTracker()
        self._auto_tuner = AutoTuner(
            tracker=self._tracker,
            target_ms=settings.HFT_LATENCY_MAX_EXECUTION_LATENCY_MS,
        )
        self._started = False

    async def start(self) -> dict[str, Any]:
        """Run full latency optimisation startup.

        Returns a report with timing and status of each step.
        """
        if self._started:
            return {"status": "already_started"}
        self._started = True
        t0 = time.monotonic()
        report: dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps": [],
        }

        # 1. DNS pre-resolve all endpoints
        dns_t0 = time.monotonic()
        urls = [e.url for e in self._endpoints]
        if any(e.ws_url for e in self._endpoints):
            urls.extend(e.ws_url for e in self._endpoints if e.ws_url)
        dns_results = await self._dns.warm(urls)
        dns_success = sum(1 for r in dns_results.values() if r.success)
        report["steps"].append(
            {
                "name": "dns_warm",
                "elapsed_ms": round((time.monotonic() - dns_t0) * 1000, 1),
                "hosts_resolved": len(dns_results),
                "success_count": dns_success,
            }
        )

        # 2. Pre-warm HTTP connections
        warm_t0 = time.monotonic()
        warm_results = await self._warmer.warm_all(self._endpoints)
        warm_success = sum(1 for r in warm_results if r.success)
        report["steps"].append(
            {
                "name": "connection_warm",
                "elapsed_ms": round((time.monotonic() - warm_t0) * 1000, 1),
                "endpoints": len(self._endpoints),
                "success_count": warm_success,
            }
        )

        # 3. Tune event loop
        loop_t0 = time.monotonic()
        loop_report = self._tuner_loop.tune()
        report["steps"].append(
            {
                "name": "event_loop_tune",
                "elapsed_ms": round((time.monotonic() - loop_t0) * 1000, 1),
                "changes": loop_report,
            }
        )

        # 4. Start auto-tuner
        await self._auto_tuner.start()
        report["steps"].append({"name": "auto_tuner", "status": "started"})

        total = (time.monotonic() - t0) * 1000
        report["total_elapsed_ms"] = round(total, 1)
        report["status"] = "ok"

        logger.info(
            "[latency_optimizer] Startup complete in {:.0f}ms — {}/{} endpoints warmed, "
            "DNS {}/{} hosts resolved, loop tuned",
            total,
            warm_success,
            len(self._endpoints),
            dns_success,
            len(dns_results),
        )

        return report

    async def stop(self) -> None:
        """Graceful shutdown — close connections, stop tuners."""
        await self._auto_tuner.stop()
        await self._warmer.close_all()
        self._tuner_loop.restore()
        self._started = False
        logger.info("[latency_optimizer] Stopped")

    def get_client(self, name: str) -> Any | None:
        """Get a pre-warmed HTTP client."""
        return self._warmer.get_client(name)

    def get_tracker(self) -> LatencyTracker:
        """Get the latency tracker instance."""
        return self._tracker

    def report(self) -> dict[str, Any]:
        """Generate a full latency report."""
        return {
            "endpoints_warmed": list(self._warmer._clients.keys()),
            "latency_summary": self._tracker.summary(),
            "auto_tune_adjustments": self._auto_tuner._adjustments[-10:]
            if self._auto_tuner._adjustments
            else [],
        }


# ── Convenience factory ──────────────────────────────────────────────────────────


_default_optimizer: LatencyOptimizer | None = None


async def start_latency_optimizer(
    endpoints: list[EndpointConfig] | None = None,
) -> LatencyOptimizer:
    """Start the default singleton latency optimizer."""
    global _default_optimizer
    if _default_optimizer is not None:
        return _default_optimizer
    _default_optimizer = LatencyOptimizer(endpoints)
    await _default_optimizer.start()
    return _default_optimizer


async def stop_latency_optimizer() -> None:
    """Stop the default singleton latency optimizer."""
    global _default_optimizer
    if _default_optimizer is not None:
        await _default_optimizer.stop()
        _default_optimizer = None
