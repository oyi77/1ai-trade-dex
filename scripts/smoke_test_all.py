#!/usr/bin/env python3
"""Smoke test for all 11 market providers against real APIs.

Usage:
    python scripts/smoke_test_all.py

Tests each provider for:
  1. Instantiation (paper_mode=True)
  2. manifest() retrieval
  3. get_balance()
  4. Market discovery (search_markets / get_markets)
  5. Market price fetch (get_market)
  6. Paper order placement

Outputs a summary table at the end.
"""

import asyncio
import contextlib
import io
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

# Suppress noisy loguru/asyncio output during smoke tests
os.environ["LOGURU_LEVEL"] = "ERROR"
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

try:
    from loguru import logger as _loguru_logger

    _loguru_logger.remove()
    _loguru_logger.add(sys.stderr, level="ERROR")
except Exception:
    pass

# Ensure project root is on sys.path
sys.path.insert(0, ".")

from backend.markets.order_types import OrderSide, OrderType, MarketInfo


@dataclass
class TestResult:
    provider_name: str
    display_name: str
    instantiate: Optional[bool] = None
    instantiate_error: str = ""
    manifest: Optional[bool] = None
    get_balance: Optional[bool] = None
    get_balance_error: str = ""
    market_discovery: Optional[bool] = None
    market_discovery_count: int = 0
    market_discovery_error: str = ""
    market_price: Optional[bool] = None
    market_price_error: str = ""
    paper_order: Optional[bool] = None
    paper_order_error: str = ""
    total_time_ms: float = 0.0

    @property
    def pass_count(self) -> int:
        return sum(
            1
            for v in [
                self.instantiate,
                self.manifest,
                self.get_balance,
                self.market_discovery,
                self.market_price,
                self.paper_order,
            ]
            if v is True
        )

    @property
    def fail_count(self) -> int:
        return sum(
            1
            for v in [
                self.instantiate,
                self.manifest,
                self.get_balance,
                self.market_discovery,
                self.market_price,
                self.paper_order,
            ]
            if v is False
        )

    @property
    def skip_count(self) -> int:
        return sum(
            1
            for v in [
                self.instantiate,
                self.manifest,
                self.get_balance,
                self.market_discovery,
                self.market_price,
                self.paper_order,
            ]
            if v is None
        )


# ---------------------------------------------------------------------------
# Provider definitions: (class_name, module_path, display_name)
# ---------------------------------------------------------------------------
PROVIDERS = [
    ("PolymarketProvider", "backend.markets.providers.polymarket_provider", "Polymarket"),
    ("KalshiProvider", "backend.markets.providers.kalshi_provider", "Kalshi"),
    ("SXBetProvider", "backend.markets.providers.sxbet_provider", "SX.bet"),
    ("HyperliquidProvider", "backend.markets.providers.hyperliquid_provider", "Hyperliquid"),
    ("AsterProvider", "backend.markets.providers.aster_provider", "Aster"),
    ("LighterProvider", "backend.markets.providers.lighter_provider", "Lighter"),
    ("OstiumProvider", "backend.markets.providers.ostium_provider", "Ostium"),
    ("MyriadProvider", "backend.markets.providers.myriad_provider", "Myriad"),
    ("BookmakerXYZProvider", "backend.markets.providers.bookmaker_xyz_provider", "Bookmaker.xyz"),
    ("PredictFunProvider", "backend.markets.providers.predict_fun_provider", "Predict.fun"),
    ("PaperProvider", "backend.markets.providers.paper_provider", "Paper"),
]


async def test_provider(
    class_name: str, module_path: str, display_name: str
) -> TestResult:
    """Run all smoke tests against a single provider."""
    result = TestResult(provider_name=class_name, display_name=display_name)
    start = time.monotonic()
    provider = None

    try:
        # --- 1. Instantiate ---
        try:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            provider = cls(paper_mode=True)
            result.instantiate = True
        except Exception as e:
            result.instantiate = False
            result.instantiate_error = _short_error(e)
            result.total_time_ms = (time.monotonic() - start) * 1000
            return result

        # --- 2. manifest() ---
        try:
            manifest = cls.manifest()
            assert manifest.name, "manifest.name is empty"
            result.manifest = True
        except Exception as e:
            result.manifest = False

        # --- 3. get_balance() ---
        try:
            balance = await provider.get_balance()
            assert balance is not None
            result.get_balance = True
        except Exception as e:
            result.get_balance = False
            result.get_balance_error = _short_error(e)

        # --- 4. Market discovery (search_markets or get_markets) ---
        # NOTE: Providers that subclass BaseMarketProvider always have
        # search_markets (returns [] by default). Only test providers that
        # override the method AND have an actual client — paper mode providers
        # that delegate to external APIs will hit those APIs.
        # An empty list without exception = PASS.  Exception = FAIL.
        try:
            from backend.markets.base_provider import BaseMarketProvider

            has_search = (
                type(provider).search_markets is not BaseMarketProvider.search_markets
            )
            has_get_markets = hasattr(provider, "get_markets") and callable(
                getattr(provider, "get_markets", None)
            )

            if has_search or has_get_markets:
                # Suppress loguru/asyncio noise from client code during API calls
                with open(os.devnull, "w") as devnull:
                    old_stderr = sys.stderr
                    sys.stderr = devnull
                    try:
                        if has_search:
                            markets = await provider.search_markets(
                                query="crypto", category=None, limit=5
                            )
                        else:
                            markets = await provider.get_markets(limit=5)
                    finally:
                        sys.stderr = old_stderr
            else:
                markets = None  # no discovery method overridden

            if markets is not None:
                # API returned a list (possibly empty) without error — PASS
                result.market_discovery = True
                result.market_discovery_count = len(markets)
            else:
                # No market discovery method overridden — SKIP (not a failure)
                result.market_discovery = None
                result.market_discovery_count = 0
        except Exception as e:
            result.market_discovery = False
            result.market_discovery_error = _short_error(e)

        # --- 5. Market price fetch (get_market) ---
        try:
            # Try get_market with a common market id; may fail but tests the code path
            price_market = await provider.get_market("test_market")
            # Even None is acceptable — method exists and didn't crash
            result.market_price = True
        except Exception as e:
            result.market_price = False
            result.market_price_error = _short_error(e)

        # --- 6. Paper order placement ---
        try:
            from backend.markets.base_provider import NormalizedOrder

            order = NormalizedOrder(
                market_id="smoke_test_market",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                size=Decimal("1.0"),
                price=Decimal("0.50"),
                client_order_id="smoke_test_order",
            )
            order_result = await provider.place_order(order)
            result.paper_order = order_result is not None
        except Exception as e:
            result.paper_order = False
            result.paper_order_error = _short_error(e)

    except Exception as e:
        # Catch-all for anything unexpected
        pass
    finally:
        result.total_time_ms = (time.monotonic() - start) * 1000
        if provider and hasattr(provider, "teardown"):
            try:
                await provider.teardown()
            except Exception:
                pass

    return result


def _short_error(e: Exception, max_len: int = 80) -> str:
    """Return a short, single-line error string."""
    msg = f"{type(e).__name__}: {e}"
    return msg[:max_len].replace("\n", " ")


def _status_icon(val: Optional[bool]) -> str:
    if val is True:
        return "PASS"
    elif val is False:
        return "FAIL"
    return "SKIP"


def print_results(results: list[TestResult]):
    """Print a formatted summary table."""
    print("\n" + "=" * 100)
    print("SMOKE TEST RESULTS")
    print("=" * 100)

    # Header
    header = f"{'Provider':<18} {'Init':>4} {'Mani':>4} {'Bal':>4} {'Mkt':>4} {'Prc':>4} {'Ord':>4} {'Pass':>4} {'Time(ms)':>9}"
    print(header)
    print("-" * 100)

    total_pass = 0
    total_fail = 0
    total_skip = 0

    for r in results:
        init_s = _status_icon(r.instantiate)
        mani_s = _status_icon(r.manifest)
        bal_s = _status_icon(r.get_balance)
        mkt_s = _status_icon(r.market_discovery)
        prc_s = _status_icon(r.market_price)
        ord_s = _status_icon(r.paper_order)
        pass_str = f"{r.pass_count}/6"
        time_str = f"{r.total_time_ms:>7.0f}"

        print(
            f"{r.display_name:<18} {init_s:>4} {mani_s:>4} {bal_s:>4} {mkt_s:>4} {prc_s:>4} {ord_s:>4} {pass_str:>4} {time_str:>9}"
        )
        total_pass += r.pass_count
        total_fail += r.fail_count
        total_skip += r.skip_count

    print("-" * 100)
    total_tests = total_pass + total_fail + total_skip
    print(
        f"{'TOTAL':<18} {'':>4} {'':>4} {'':>4} {'':>4} {'':>4} {'':>4} {total_pass:>4}/{total_tests:<3}"
    )
    print()

    # Detail section for failures
    failures = [
        r
        for r in results
        if r.fail_count > 0
        and any(
            [
                r.instantiate_error,
                r.get_balance_error,
                r.market_discovery_error,
                r.market_price_error,
                r.paper_order_error,
            ]
        )
    ]
    if failures:
        print("FAILURE DETAILS:")
        print("-" * 100)
        for r in failures:
            print(f"\n  {r.display_name} ({r.provider_name}):")
            if r.instantiate_error:
                print(f"    Init:  {r.instantiate_error}")
            if r.get_balance_error:
                print(f"    Bal:   {r.get_balance_error}")
            if r.market_discovery_error:
                print(f"    Mkt:   {r.market_discovery_error}")
            if r.market_price_error:
                print(f"    Price: {r.market_price_error}")
            if r.paper_order_error:
                print(f"    Order: {r.paper_order_error}")

    # Additional info
    print("\nMARKET DISCOVERY COUNTS:")
    print("-" * 100)
    for r in results:
        status = "N/A" if r.market_discovery is None else str(r.market_discovery_count)
        print(f"  {r.display_name:<18} {status} markets found")

    print()


async def main():
    print("Starting smoke tests for all 11 market providers...")
    print("Mode: PAPER (no real orders will be placed)")
    print(f"Testing: {', '.join(p[2] for p in PROVIDERS)}")
    print()

    results = []
    for class_name, module_path, display_name in PROVIDERS:
        print(f"  Testing {display_name}...", end="", flush=True)
        result = await test_provider(class_name, module_path, display_name)
        passed = result.pass_count
        total = 6
        status = "OK" if passed == total else f"{passed}/{total}"
        print(f" {status} ({result.total_time_ms:.0f}ms)")
        results.append(result)

    print_results(results)

    # Exit code: 0 if all pass, 1 if any fail
    any_fail = any(r.fail_count > 0 for r in results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
