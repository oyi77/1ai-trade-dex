"""Quick test script to verify Polymarket testnet mode with Builder Program credentials.
Note: Testnet mode uses MAINNET CLOB (clob.polymarket.com) with Builder auth for gasless trading.
The staging CLOB (clob-staging.polymarket.com) is non-functional; there is no separate testnet CLOB.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("TRADING_MODE", "testnet")

from dotenv import load_dotenv

load_dotenv()

from backend.data.polymarket_clob import PolymarketCLOB
from backend.config import settings


async def test_testnet():
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    builder_key = os.getenv("POLYMARKET_BUILDER_API_KEY")
    builder_secret = os.getenv("POLYMARKET_BUILDER_SECRET")
    builder_pass = os.getenv("POLYMARKET_BUILDER_PASSPHRASE")
    builder_address = os.getenv("POLYMARKET_BUILDER_ADDRESS")

    # NOTE: Testnet mode uses mainnet CLOB with Builder auth (gasless trading).
    print("=" * 60)
    print("POLYMARKET TESTNET MODE TEST (Builder Program on Mainnet CLOB)")
    print("=" * 60)
    print("  CLOB Host:  https://clob.polymarket.com")
    print("  Chain ID:   137 (Polygon mainnet)")
    print(f"  PK set:     {'YES' if pk else 'NO'}")
    print(f"  Builder key: {'YES' if builder_key else 'NO'}")
    print()
    print("NOTE: Testnet mode uses mainnet CLOB with Builder auth (gasless trading).")
    print()

    if not pk:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set in .env")
        return False

    async with PolymarketCLOB(
        private_key=pk,
        mode="testnet",
        builder_api_key=builder_key,
        builder_secret=builder_secret,
        builder_passphrase=builder_pass,
        builder_address=builder_address,
        signature_type=settings.POLYMARKET_SIGNATURE_TYPE,
    ) as clob:
        print(f"  Account:    {clob._account.address if clob._account else 'N/A'}")
        print(f"  Mode:       {clob.mode}")
        print(
            f"  ClobClient: {'initialized' if clob._clob_client else 'NOT initialized'}"
        )
        print()

        # Test 1: Fetch markets (should work on mainnet CLOB)
        print("TEST 1: Fetch market list from mainnet CLOB...")
        try:
            resp = await clob._http.get(
                f"{clob._clob_host}/markets", params={"limit": 5}
            )
            resp.raise_for_status()
            data = resp.json()
            count = len(data) if isinstance(data, list) else "unknown"
            print(f"  ✓ Fetched {count} markets from mainnet CLOB")
        except Exception as e:
            print(f"  ✗ Failed: {e}")

        # Test 2: CLOB client API key derivation
        print()
        print("TEST 2: Derive API credentials from PK...")
        try:
            if clob._clob_client:
                api_creds = await clob.create_or_derive_api_key()
                if api_creds:
                    print(f"  ✓ API Key derived: {api_creds.api_key[:20]}...")
                    print(f"  ✓ API Secret: {api_creds.api_secret[:10]}...")
                else:
                    print("  ✗ API credential derivation returned None")
            else:
                print("  ✗ ClobClient not initialized")
        except Exception as e:
            print(f"  ✗ Failed: {e}")

        # Test 3: Check wallet balance on mainnet
        print()
        print("TEST 3: Check wallet balance...")
        try:
            if clob._clob_client:
                balance = (
                    clob._clob_client.get_balance_allowance(
                        BalanceAllowanceParams(
                            asset_type=AssetType.COLLATERAL,
                        )
                    )
                    if hasattr(clob._clob_client, "get_balance_allowance")
                    else None
                )
                if balance:
                    usdc_balance = float(balance.get("balance", 0)) / 1e6
                    print(f"  ✓ USDC Balance: {usdc_balance:.2f}")
                else:
                    print("  ~ No balance data")
            else:
                print("  ✗ ClobClient not initialized")
        except Exception as e:
            print(f"  ~ Balance check failed: {e}")

        # Test 4: Builder auth check
        print()
        print("TEST 4: Builder Program authentication...")
        try:
            if clob._clob_client and builder_key:
                can_builder = bool(clob._clob_client.builder_config and clob._clob_client.builder_config.builder_address)
                print(f"  ✓ Builder auth capable: {can_builder}")
            else:
                print("  ✗ Builder credentials not configured")
        except Exception as e:
            print(f"  ~ Builder auth check: {e}")

    print()
    print("=" * 60)
    print("TESTNET MODE TEST COMPLETE")
    print("=" * 60)
    print()
    print("NEXT STEPS:")
    print("  1. Fund your wallet with USDC on Polygon mainnet")
    print("  2. Set TRADING_MODE=testnet in .env")
    print("  3. Start the bot: python -m backend")
    print(
        "  4. Monitor dashboard - testnet trades will be REAL but gasless via Builder Program"
    )
    return True


if __name__ == "__main__":
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
    except ImportError:
        BalanceAllowanceParams = None
        AssetType = None
    asyncio.run(test_testnet())
