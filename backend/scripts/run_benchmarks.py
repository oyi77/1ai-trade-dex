#!/usr/bin/env python3
"""G-23: Performance benchmarks for PolyEdge backend.

Runs key performance benchmarks:
- Trade execution latency
- Market scan throughput
- Settlement processing time

Usage:
    python backend/scripts/run_benchmarks.py
    python backend/scripts/run_benchmarks.py --iterations 100
    python backend/scripts/run_benchmarks.py --benchmark latency
"""

import asyncio
import argparse
import statistics
import time
from datetime import datetime, timezone
from typing import Callable


def benchmark_sync(name: str, func: Callable, iterations: int = 100) -> dict:
    """Benchmark a synchronous function."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    return {
        "name": name,
        "iterations": iterations,
        "total_s": sum(times),
        "mean_ms": statistics.mean(times) * 1000,
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(iterations * 0.95)] * 1000,
        "p99_ms": sorted(times)[int(iterations * 0.99)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
        "stdev_ms": statistics.stdev(times) * 1000 if len(times) > 1 else 0,
    }


async def benchmark_async(name: str, func: Callable, iterations: int = 100) -> dict:
    """Benchmark an async function."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    return {
        "name": name,
        "iterations": iterations,
        "total_s": sum(times),
        "mean_ms": statistics.mean(times) * 1000,
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(iterations * 0.95)] * 1000,
        "p99_ms": sorted(times)[int(iterations * 0.99)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
        "stdev_ms": statistics.stdev(times) * 1000 if len(times) > 1 else 0,
    }


def print_results(results: dict) -> None:
    """Print benchmark results in a formatted table."""
    print(f"\n{'=' * 60}")
    print(f"Benchmark: {results['name']}")
    print(f"{'=' * 60}")
    print(f"  Iterations:  {results['iterations']}")
    print(f"  Total:       {results['total_s']:.3f}s")
    print(f"  Mean:        {results['mean_ms']:.2f}ms")
    print(f"  Median:      {results['median_ms']:.2f}ms")
    print(f"  P95:         {results['p95_ms']:.2f}ms")
    print(f"  P99:         {results['p99_ms']:.2f}ms")
    print(f"  Min:         {results['min_ms']:.2f}ms")
    print(f"  Max:         {results['max_ms']:.2f}ms")
    print(f"  Stdev:       {results['stdev_ms']:.2f}ms")


# --- Benchmark functions ---


def bench_config_load():
    """Benchmark config loading."""
    from backend.config import Settings

    Settings()


def bench_circuit_breaker_check():
    """Benchmark circuit breaker state check."""
    from backend.core.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("bench_test")
    cb.state  # Just read state


def bench_strategy_gate_check():
    """Benchmark strategy gate stage check (mocked DB)."""
    from unittest.mock import MagicMock
    from backend.core.strategy_gate import StrategyGate

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    StrategyGate.get_stage("bench_strategy", db)


def bench_risk_calculation():
    """Benchmark risk limit calculation (mocked)."""
    from unittest.mock import MagicMock
    from backend.core.strategy_gate import check_risk_and_disable

    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    db.execute.return_value.scalar.return_value = 0
    check_risk_and_disable(db)


def bench_slug_validation():
    """Benchmark crypto slug validation."""
    from backend.data.btc_markets import is_valid_crypto_slug

    is_valid_crypto_slug("btc-updown-5m-1716000000", "btc")


def bench_slug_generation():
    """Benchmark window slug computation."""
    from backend.data.btc_markets import _compute_window_slugs

    _compute_window_slugs("btc", count=6)


def bench_unified_market_view():
    """Benchmark UnifiedMarketView creation."""
    from backend.data.market_types import UnifiedMarketView

    UnifiedMarketView(
        slug="test-market",
        platform="polymarket",
        title="Test Market",
        yes_price=0.55,
        no_price=0.45,
        volume=10000.0,
        closes_at=datetime.now(timezone.utc),
    )


async def bench_gamma_single_page():
    """Benchmark Gamma API single page fetch (mocked)."""
    from unittest.mock import AsyncMock, patch

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = AsyncMock(
            status_code=200,
            json=lambda: [{"id": i, "slug": f"market-{i}"} for i in range(100)],
            raise_for_status=lambda: None,
        )
        from backend.data.gamma import fetch_markets

        await fetch_markets(limit=100)


def bench_market_scanner_parse():
    """Benchmark market event parsing."""
    from backend.data.btc_markets import _parse_event_to_crypto_market

    event = {
        "slug": "btc-updown-5m-1716000000",
        "startDate": "2026-05-18T00:00:00Z",
        "endDate": "2026-05-18T00:05:00Z",
        "markets": [
            {
                "id": "test-market-id",
                "outcomePrices": '["0.55","0.45"]',
                "clobTokenIds": '["token-up","token-down"]',
                "volume": 50000,
                "closed": False,
            }
        ],
    }
    _parse_event_to_crypto_market(event, "btc")


# --- Main ---

BENCHMARKS = {
    "latency": [
        ("Config Load", bench_config_load, False),
        ("Circuit Breaker Check", bench_circuit_breaker_check, False),
        ("Strategy Gate Check", bench_strategy_gate_check, False),
        ("Risk Calculation", bench_risk_calculation, False),
        ("Slug Validation", bench_slug_validation, False),
        ("Slug Generation", bench_slug_generation, False),
        ("UnifiedMarketView Creation", bench_unified_market_view, False),
        ("Market Event Parsing", bench_market_scanner_parse, False),
    ],
    "throughput": [
        ("Gamma API Single Page", bench_gamma_single_page, True),
    ],
}


async def main():
    parser = argparse.ArgumentParser(description="PolyEdge performance benchmarks")
    parser.add_argument(
        "--iterations", type=int, default=100, help="Iterations per benchmark"
    )
    parser.add_argument(
        "--benchmark", choices=["latency", "throughput", "all"], default="all"
    )
    args = parser.parse_args()

    print("PolyEdge Performance Benchmarks")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"Iterations: {args.iterations}")

    categories = (
        [args.benchmark] if args.benchmark != "all" else list(BENCHMARKS.keys())
    )

    for category in categories:
        benchmarks = BENCHMARKS.get(category, [])
        print(f"\n{'#' * 60}")
        print(f"# Category: {category.upper()}")
        print(f"{'#' * 60}")

        for name, func, is_async in benchmarks:
            try:
                if is_async:
                    results = await benchmark_async(name, func, args.iterations)
                else:
                    results = benchmark_sync(name, func, args.iterations)
                print_results(results)
            except Exception as e:
                print(f"\n  FAILED: {name} — {e}")

    print(f"\n{'=' * 60}")
    print("BENCHMARK COMPLETE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
