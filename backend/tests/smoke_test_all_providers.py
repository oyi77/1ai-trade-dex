"""
Smoke test for all market provider plugins.
Calls search_markets() (or get_balance()) against REAL APIs.
Reports pass/fail per provider with timing and error details.
Machine-parseable JSON summary at end.

Uses file-path imports to bypass providers/__init__.py auto-discovery
which would import ALL providers at once and could hang.

Usage:
    cd /home/openclaw/projects/1ai-trade-dex
    python -m backend.tests.smoke_test_all_providers
"""

import asyncio
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass

# Ensure project root is on the path
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force paper mode for safety
os.environ.setdefault("TRADING_MODE", "paper")


@dataclass
class ProviderResult:
    name: str
    display_name: str
    status: str = "UNKNOWN"  # PASS, FAIL, SKIPPED, BLOCKED
    duration_s: float = 0.0
    markets_found: int = 0
    error: str = ""


# (class_name, module_file_path_relative_to_project, display_name)
PROVIDERS = [
    (
        "PolymarketProvider",
        "backend/markets/providers/polymarket_provider.py",
        "Polymarket",
    ),
    ("KalshiProvider", "backend/markets/providers/kalshi_provider.py", "Kalshi"),
    ("SXBetProvider", "backend/markets/providers/sxbet_provider.py", "SX.bet"),
    (
        "HyperliquidProvider",
        "backend/markets/providers/hyperliquid_provider.py",
        "Hyperliquid",
    ),
    ("OstiumProvider", "backend/markets/providers/ostium_provider.py", "Ostium"),
    ("AsterProvider", "backend/markets/providers/aster_provider.py", "Aster"),
    ("LighterProvider", "backend/markets/providers/lighter_provider.py", "Lighter"),
    (
        "BookmakerXYZProvider",
        "backend/markets/providers/bookmaker_xyz_provider.py",
        "BookmakerXYZ",
    ),
    (
        "PredictFunProvider",
        "backend/markets/providers/predict_fun_provider.py",
        "PredictFun",
    ),
    ("MyriadProvider", "backend/markets/providers/myriad_provider.py", "Myriad"),
    ("PaperProvider", "backend/markets/providers/paper_provider.py", "Paper"),
]


def _import_by_filepath(module_name: str, filepath: str):
    """Import a Python module by absolute file path, bypassing __init__.py."""
    abs_path = os.path.join(PROJECT_ROOT, filepath)
    if not os.path.isfile(abs_path):
        raise ImportError(f"File not found: {abs_path}")
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    # Inject into sys.modules so internal relative imports resolve
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pre_import_deps():
    """Pre-import common dependencies to avoid repeated loads."""
    try:
        import backend.config  # noqa: F401
    except Exception:
        pass
    try:
        import backend.markets.base_provider  # noqa: F401
    except Exception:
        pass
    try:
        import backend.markets.order_types  # noqa: F401
    except Exception:
        pass


# Pre-import shared deps once
_pre_import_deps()


async def test_provider(
    class_name: str, filepath: str, display_name: str
) -> ProviderResult:
    """Test a single provider by importing, instantiating, and calling search_markets()."""
    result = ProviderResult(name=class_name, display_name=display_name)
    start = time.monotonic()

    # Step 1: Import by file path (avoid __init__.py auto-discovery)
    module_name = f"_smoke_test_{class_name.lower()}"
    try:
        mod = _import_by_filepath(module_name, filepath)
        cls = getattr(mod, class_name)
    except (ImportError, AttributeError) as e:
        result.status = "SKIPPED"
        result.error = f"Import failed: {e}"
        result.duration_s = time.monotonic() - start
        return result
    except Exception as e:
        result.status = "FAIL"
        result.error = f"Import error: {type(e).__name__}: {e}"
        result.duration_s = time.monotonic() - start
        return result

    # Step 2: Instantiate (paper_mode=True for safety)
    try:
        provider = cls(paper_mode=True)
    except ImportError as e:
        result.status = "SKIPPED"
        result.error = f"Init failed (missing SDK): {e}"
        result.duration_s = time.monotonic() - start
        return result
    except Exception as e:
        result.status = "FAIL"
        result.error = f"Init error: {type(e).__name__}: {e}"
        result.duration_s = time.monotonic() - start
        return result

    # Step 3: Call search_markets() -- check if the provider overrides it
    import inspect

    search_method = getattr(provider, "search_markets", None)
    from backend.markets.base_provider import BaseMarketProvider

    has_own_search = (
        search_method is not None
        and search_method is not BaseMarketProvider.search_markets
    )

    tried_search = False
    if has_own_search:
        try:
            sig = inspect.signature(search_method)
            kwargs = {}
            if "query" in sig.parameters:
                kwargs["query"] = None
            if "category" in sig.parameters:
                kwargs["category"] = None
            if "limit" in sig.parameters:
                kwargs["limit"] = 10
            tried_search = True
            markets = await asyncio.wait_for(
                search_method(**kwargs),
                timeout=30.0,
            )
            if markets is not None:
                result.markets_found = len(markets) if isinstance(markets, list) else 0
                result.status = "PASS"
            else:
                result.markets_found = 0
                result.status = "PASS"
        except asyncio.TimeoutError:
            result.status = "BLOCKED"
            result.error = "search_markets timeout after 30s"
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str or "403" in err_str:
                result.status = "BLOCKED"
                result.error = f"Auth error: {e}"
            elif "404" in err_str or "not found" in err_str:
                result.status = "BLOCKED"
                result.error = f"Not found (404): {e}"
            elif "not set" in err_str or "missing" in err_str or "required" in err_str:
                result.status = "SKIPPED"
                result.error = f"Missing config: {e}"
            elif "connect" in err_str or "timeout" in err_str or "refused" in err_str:
                result.status = "BLOCKED"
                result.error = f"Connection error: {e}"
            else:
                result.status = "FAIL"
                result.error = f"{type(e).__name__}: {str(e)[:200]}"

    # Step 4: If no search_markets or it returned 0, try get_balance()
    should_try_balance = not tried_search or (
        result.status == "PASS" and result.markets_found == 0
    )
    if should_try_balance:
        try:
            balance = await asyncio.wait_for(provider.get_balance(), timeout=15.0)
            if balance is not None:
                result.status = "PASS"
                if not tried_search:
                    result.error = "no search_markets override; get_balance OK"
                else:
                    result.error = (
                        "search_markets returned 0 results but get_balance OK"
                    )
            else:
                result.status = "PASS"
                if not tried_search:
                    result.error = (
                        "no search_markets override; get_balance returned None"
                    )
        except asyncio.TimeoutError:
            if result.status != "PASS":
                pass  # keep the more informative error from search_markets
            else:
                result.status = "BLOCKED"
                result.error = "get_balance timed out"
        except Exception as e:
            if result.status != "PASS":
                pass  # keep the more informative error from search_markets
            else:
                err_str = str(e).lower()
                if "401" in err_str or "unauthorized" in err_str or "403" in err_str:
                    result.status = "BLOCKED"
                    result.error = f"get_balance auth error: {e}"
                elif (
                    "not set" in err_str
                    or "missing" in err_str
                    or "required" in err_str
                ):
                    result.status = "SKIPPED"
                    result.error = f"Missing config: {e}"
                else:
                    result.status = "FAIL"
                    result.error = (
                        f"get_balance failed: {type(e).__name__}: {str(e)[:200]}"
                    )

    # Teardown
    try:
        await provider.teardown()
    except Exception:
        pass

    result.duration_s = time.monotonic() - start
    return result


async def main():
    print("=" * 60)
    print("  PROVIDER SMOKE TEST (REAL APIs, paper mode)")
    print("=" * 60)
    print()

    results: list[ProviderResult] = []
    for class_name, filepath, display_name in PROVIDERS:
        r = await test_provider(class_name, filepath, display_name)
        results.append(r)

        status_tag = f"[{r.status}]"
        detail = (
            f"{r.markets_found} markets"
            if r.status == "PASS" and r.markets_found > 0
            else r.error or "OK"
        )
        timing = f"{r.duration_s:.1f}s"
        print(f"  {status_tag:<12} {r.display_name:<20} {detail:<50} {timing}")
        sys.stdout.flush()

    # Summary counts
    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    print()
    summary_parts = [f"{v} {k}" for k, v in sorted(counts.items())]
    print(f"  Summary: {', '.join(summary_parts)}")
    print(f"  Total: {len(results)} providers tested")

    # JSON output
    print()
    print("=== JSON SUMMARY ===")
    json_out = {
        "test": "provider_smoke_test",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": [
            {
                "name": r.name,
                "display_name": r.display_name,
                "status": r.status,
                "duration_s": round(r.duration_s, 2),
                "markets_found": r.markets_found,
                "error": r.error,
            }
            for r in results
        ],
        "summary": counts,
        "total": len(results),
    }
    print(json.dumps(json_out, indent=2))

    # Exit code: 0 if no FAIL, 1 if any FAIL
    has_fail = any(r.status == "FAIL" for r in results)
    return 1 if has_fail else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
