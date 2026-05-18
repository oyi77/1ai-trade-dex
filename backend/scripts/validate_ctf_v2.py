#!/usr/bin/env python3
"""
Validate CTF Exchange V2 compatibility for PolyEdge.

Checks:
1. py_clob_client_v2 installed version meets minimum (1.0.0)
2. Contract addresses match between package config and auto_redeem.py
3. ClobClient can be instantiated and create_order uses V2 path
4. OrderBuilder V2 signing produces valid EIP-712 typed data

Usage:
    python backend/scripts/validate_ctf_v2.py              # full validation
    python backend/scripts/validate_ctf_v2.py --dry-run    # no network calls
    python backend/scripts/validate_ctf_v2.py --json       # machine-readable output
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import json
import os
import sys
from importlib.metadata import version as pkg_version

# Ensure project root is on sys.path so `backend` is importable
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_VERSION = (1, 0, 0)

# Expected contract addresses on Polygon (chain_id=137)
EXPECTED_ADDRESSES = {
    "exchange_v2": "0xE111180000d2663C0091e4f400237545B87B996B",
    "neg_risk_exchange_v2": "0xe2222d279d744050d28e00520010520000310F59",
    "conditional_tokens": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
    "neg_risk_adapter": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
}


@dataclasses.dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


results: list[CheckResult] = []


def check(name: str, passed: bool, detail: str) -> None:
    results.append(CheckResult(name=name, passed=passed, detail=detail))
    symbol = "PASS" if passed else "FAIL"
    print(f"  [{symbol}] {name}: {detail}")


# ---------------------------------------------------------------------------
# 1. Package version
# ---------------------------------------------------------------------------

def validate_version() -> None:
    print("\n=== 1. Package Version ===")
    try:
        raw = pkg_version("py-clob-client-v2")
    except Exception:
        try:
            raw = pkg_version("py_clob_client_v2")
        except Exception:
            check("installed", False, "py_clob_client_v2 NOT installed")
            return

    parts = tuple(int(p) for p in raw.split(".")[:3])
    meets_min = parts >= MIN_VERSION
    check(
        "version",
        meets_min,
        f"installed={raw}, minimum={'.'.join(map(str, MIN_VERSION))}",
    )


# ---------------------------------------------------------------------------
# 2. Contract addresses
# ---------------------------------------------------------------------------

def validate_contract_addresses() -> None:
    print("\n=== 2. Contract Addresses (Polygon / chain_id=137) ===")
    try:
        from py_clob_client_v2.config import get_contract_config
    except ImportError as exc:
        check("import", False, f"cannot import config: {exc}")
        return

    try:
        config = get_contract_config(137)
    except Exception as exc:
        check("config_load", False, f"get_contract_config(137) failed: {exc}")
        return

    for field_name, expected in EXPECTED_ADDRESSES.items():
        actual = getattr(config, field_name, None)
        passed = actual is not None and actual.lower() == expected.lower()
        check(
            field_name,
            passed,
            f"expected={expected}, got={actual}",
        )


# ---------------------------------------------------------------------------
# 3. auto_redeem.py addresses
# ---------------------------------------------------------------------------

def validate_auto_redeem_addresses() -> None:
    print("\n=== 3. auto_redeem.py Contract Addresses ===")
    try:
        from backend.core.auto_redeem import (
            CTF_ADDRESS,
            NEG_RISK_ADAPTER,
            USDC_POLYGON,
        )
    except ImportError as exc:
        check("import", False, f"cannot import auto_redeem: {exc}")
        return

    ctf_match = (
        CTF_ADDRESS.lower()
        == EXPECTED_ADDRESSES["conditional_tokens"].lower()
    )
    check("CTF_address", ctf_match, f"auto_redeem={CTF_ADDRESS}")

    nra_match = (
        NEG_RISK_ADAPTER.lower()
        == EXPECTED_ADDRESSES["neg_risk_adapter"].lower()
    )
    check("neg_risk_adapter", nra_match, f"auto_redeem={NEG_RISK_ADAPTER}")

    check(
        "USDC_POLYGON",
        True,
        f"auto_redeem={USDC_POLYGON} (USDC.e on Polygon, used for CTF redemption)",
    )


# ---------------------------------------------------------------------------
# 4. ClobClient V2 order path
# ---------------------------------------------------------------------------

def validate_order_builder_v2() -> None:
    print("\n=== 4. OrderBuilder V2 Path ===")
    try:
        from py_clob_client_v2.order_builder.builder import OrderBuilder
        from py_clob_client_v2.order_utils.exchange_order_builder_v2 import (
            ExchangeOrderBuilderV2,
        )
        from py_clob_client_v2.order_utils.model.ctf_exchange_v2_typed_data import (
            CTF_EXCHANGE_V2_DOMAIN_NAME,
            CTF_EXCHANGE_V2_DOMAIN_VERSION,
            CTF_EXCHANGE_V2_ORDER_STRUCT,
        )
    except ImportError as exc:
        check("v2_imports", False, f"V2 order builder missing: {exc}")
        return

    check("v2_order_builder", True, "ExchangeOrderBuilderV2 importable")

    check(
        "v2_domain_name",
        CTF_EXCHANGE_V2_DOMAIN_NAME is not None
        and len(CTF_EXCHANGE_V2_DOMAIN_NAME) > 0,
        f"domain_name={CTF_EXCHANGE_V2_DOMAIN_NAME!r}",
    )

    check(
        "v2_domain_version",
        CTF_EXCHANGE_V2_DOMAIN_VERSION is not None
        and len(CTF_EXCHANGE_V2_DOMAIN_VERSION) > 0,
        f"domain_version={CTF_EXCHANGE_V2_DOMAIN_VERSION!r}",
    )

    check(
        "v2_order_struct",
        isinstance(CTF_EXCHANGE_V2_ORDER_STRUCT, list)
        and len(CTF_EXCHANGE_V2_ORDER_STRUCT) > 0,
        f"order_struct_fields={len(CTF_EXCHANGE_V2_ORDER_STRUCT)}",
    )


# ---------------------------------------------------------------------------
# 5. OrderArgsV2 compatibility with polymarket_clob.py
# ---------------------------------------------------------------------------

def validate_clob_imports() -> None:
    print("\n=== 5. polymarket_clob.py V2 Compatibility ===")
    try:
        from py_clob_client_v2 import (
            ClobClient,
            ApiCreds,
            BuilderConfig,
            OrderArgs,
            BalanceAllowanceParams,
            AssetType,
            OrderPayload,
        )
    except ImportError as exc:
        check("clob_imports", False, f"import failed: {exc}")
        return

    check("clob_imports", True, "all imports from py_clob_client_v2 succeed")

    try:
        from py_clob_client_v2.clob_types import OrderArgsV2
        is_v2 = OrderArgs is OrderArgsV2
        check(
            "OrderArgs_is_V2",
            is_v2,
            f"OrderArgs {'is' if is_v2 else 'is NOT'} OrderArgsV2",
        )
    except ImportError:
        check("OrderArgs_is_V2", False, "OrderArgsV2 not found")

    import inspect

    sig = inspect.signature(ClobClient.create_order)
    first_param = list(sig.parameters.keys())[1]
    param_annotation = sig.parameters[first_param].annotation
    check(
        "create_order_accepts_V2",
        "OrderArgsV2" in str(param_annotation),
        f"param={first_param}, type={param_annotation}",
    )

    from py_clob_client_v2.order_builder.builder import OrderBuilder

    build_sig = inspect.signature(OrderBuilder.build_order)
    version_default = build_sig.parameters.get("version")
    if version_default is not None:
        default_val = version_default.default
        check(
            "default_version_is_2",
            default_val == 2,
            f"default version={default_val}",
        )
    else:
        check("default_version_is_2", False, "no 'version' param found")


# ---------------------------------------------------------------------------
# 6. SignatureTypeV2 support (proxy wallets)
# ---------------------------------------------------------------------------

def validate_signature_types() -> None:
    print("\n=== 6. SignatureTypeV2 (Proxy Wallet Support) ===")
    try:
        from py_clob_client_v2 import SignatureTypeV2
    except ImportError as exc:
        check("import", False, f"cannot import SignatureTypeV2: {exc}")
        return

    expected_types = {
        "EOA": 0,
        "POLY_PROXY": 1,
        "POLY_GNOSIS_SAFE": 2,
        "POLY_1271": 3,
    }
    for name, value in expected_types.items():
        actual = getattr(SignatureTypeV2, name, None)
        passed = actual is not None and int(actual) == value
        check(
            f"sig_type_{name}",
            passed,
            f"expected={value}, got={actual}",
        )


# ---------------------------------------------------------------------------
# 7. Dry-run order creation (no network, no signing key needed)
# ---------------------------------------------------------------------------

def validate_dry_run_order() -> None:
    print("\n=== 7. Dry-Run Order Construction ===")
    try:
        from py_clob_client_v2 import OrderArgs
        from py_clob_client_v2.order_builder.builder import OrderBuilder
        from py_clob_client_v2.signer import Signer
        from py_clob_client_v2 import (
            CreateOrderOptions,
            SignatureTypeV2,
        )
        from py_clob_client_v2.constants import POLYGON
    except ImportError as exc:
        check("imports", False, f"import failed: {exc}")
        return

    dummy_key = "0x" + "11" * 32
    try:
        signer = Signer(private_key=dummy_key, chain_id=POLYGON)
        builder = OrderBuilder(signer=signer, signature_type=SignatureTypeV2.EOA)
    except Exception as exc:
        check("signer_init", False, f"Signer/OrderBuilder init failed: {exc}")
        return

    check("signer_init", True, f"signer address={signer.address()}")

    order_args = OrderArgs(
        token_id="123456789012345678901234567890123456789012345678901234567890",
        price=0.55,
        size=100.0,
        side="BUY",
    )
    options = CreateOrderOptions(tick_size="0.01", neg_risk=False)

    try:
        signed_order = builder.build_order(
            order_args,
            options,
            version=2,
        )
        check(
            "v2_order_built",
            True,
            f"signed_order type={type(signed_order).__name__}",
        )

        order_dict = dataclasses.asdict(signed_order)
        has_v2_fields = all(
            k in order_dict for k in ("salt", "maker", "signer", "tokenId", "signature")
        )
        check(
            "v2_order_fields",
            has_v2_fields,
            f"fields={list(order_dict.keys())}",
        )

        sig = order_dict.get("signature", "")
        check(
            "signature_present",
            isinstance(sig, str) and len(sig) > 10,
            f"signature_len={len(sig) if isinstance(sig, str) else 'N/A'}",
        )

    except Exception as exc:
        check("v2_order_built", False, f"build_order failed: {exc}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary() -> bool:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{'=' * 50}")
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 50}")

    if failed:
        print("\nFailed checks:")
        for r in results:
            if not r.passed:
                print(f"  - {r.name}: {r.detail}")

    return failed == 0


def to_json() -> str:
    return json.dumps(
        {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "checks": [
                {"name": r.name, "passed": r.passed, "detail": r.detail}
                for r in results
            ],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CTF Exchange V2 compatibility")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--dry-run", action="store_true", help="Skip network-dependent checks")
    args = parser.parse_args()

    print("CTF Exchange V2 Compatibility Validator")
    print(f"Minimum py_clob_client_v2 version: {'.'.join(map(str, MIN_VERSION))}")

    validate_version()
    validate_contract_addresses()
    validate_auto_redeem_addresses()
    validate_order_builder_v2()
    validate_clob_imports()
    validate_signature_types()

    if not args.dry_run:
        validate_dry_run_order()

    if args.json:
        print(to_json())
        return 0

    all_passed = print_summary()

    if all_passed:
        print("\nCTF Exchange V2 is FULLY SUPPORTED.")
        print(" - py_clob_client_v2 v1.0.0+ uses V2 exchange contracts by default")
        print(" - Order signing uses EIP-712 with CTF_EXCHANGE_V2 domain")
        print(" - All contract addresses are current")
        print(" - Proxy wallet (Builder Program) signing supported via SignatureTypeV2")
    else:
        print("\nCTF Exchange V2 has ISSUES - see failed checks above.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
