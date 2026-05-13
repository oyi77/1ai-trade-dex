#!/usr/bin/env python3
"""
PolyEdge Mainnet Dry-Run Verification Script

Exercises ALL subsystems against the real mainnet CLOB WITHOUT placing actual orders.
Safe to run with real credentials — the order creation step sigs an order but NEVER posts it.

Tests:
  1. CLOB connectivity & wallet balance (L1 + L2 auth)
  2. Market detection (Gamma API + CLOB sampling markets)
  3. AI debate engine (real LLM call)
  4. Risk manager validation
  5. Signed order creation (NOT posted — dry run only)
  6. Settlement flow (paper mode check)
  7. Strategy executor end-to-end (paper mode, no real orders)
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["TRADING_MODE"] = "paper"

from dotenv import load_dotenv

load_dotenv()

from backend.config import settings
from backend.data.polymarket_clob import PolymarketCLOB, CLOB_HOST, CHAIN_ID
from backend.core.risk_manager import RiskManager
from backend.core.market_scanner import fetch_all_active_markets


PASSED = 0
FAILED = 0
SKIPPED = 0


def _result(test_name: str, success: bool, detail: str = ""):
    global PASSED, FAILED
    status = "✓" if success else "✗"
    if success:
        PASSED += 1
    else:
        FAILED += 1
    print(f"  {status} {test_name}: {detail}" if detail else f"  {status} {test_name}")


def _skip(test_name: str, reason: str):
    global SKIPPED
    SKIPPED += 1
    print(f"  ~ {test_name}: SKIPPED — {reason}")


async def test_clob_connectivity(clob: PolymarketCLOB):
    """Test 1: CLOB connectivity, L1/L2 auth, wallet balance."""
    print("\n[TEST 1] CLOB Connectivity & Wallet Balance")
    print("-" * 50)

    # 1a: Server time (L0 — no auth)
    try:
        resp = await clob._http.get(f"{CLOB_HOST}/time")
        resp.raise_for_status()
        server_time = resp.json()
        _result("Server time (L0)", True, f"Server time: {server_time}")
    except Exception as e:
        _result("Server time (L0)", False, str(e))

    # 1b: Fetch markets (L0 — no auth)
    try:
        resp = await clob._http.get(
            f"{CLOB_HOST}/sampling-markets", params={"next_cursor": "MA=="}
        )
        resp.raise_for_status()
        data = resp.json()
        market_count = (
            len(data.get("data", [])) if isinstance(data, dict) else "unknown"
        )
        _result("Sampling markets (L0)", True, f"{market_count} markets returned")
    except Exception as e:
        _result("Sampling markets (L0)", False, str(e))

    # 1c: API credential derivation (L1)
    if clob._clob_client:
        try:
            creds = await asyncio.to_thread(
                clob._clob_client.create_or_derive_api_creds
            )
            if creds:
                _result(
                    "API key derivation (L1)", True, f"Key: {creds.api_key[:20]}..."
                )
                # Now set creds for L2
                clob._clob_client.set_api_creds(creds)
                clob.api_key = creds.api_key
                clob.api_secret = creds.api_secret
                clob.api_passphrase = creds.api_passphrase
            else:
                _result("API key derivation (L1)", False, "Returned None")
        except Exception as e:
            _result("API key derivation (L1)", False, str(e))

        # 1d: Builder auth check
        try:
            can_builder = clob._clob_client.can_builder_auth()
            _result("Builder auth capable", can_builder, f"Builder auth: {can_builder}")
        except Exception as e:
            _result("Builder auth capable", False, str(e))

        # 1e: Wallet balance (L2)
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

            balance_resp = await asyncio.to_thread(
                clob._clob_client.get_balance_allowance,
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL),
            )
            if balance_resp and isinstance(balance_resp, dict):
                usdc_raw = float(balance_resp.get("balance", 0))
                usdc = usdc_raw / 1e6
                allowance = balance_resp.get("allowance", "0")
                _result(
                    "Wallet balance (L2)",
                    True,
                    f"USDC: ${usdc:.6f}, Allowance: {allowance}",
                )
            else:
                _result(
                    "Wallet balance (L2)", False, f"Unexpected response: {balance_resp}"
                )
        except Exception as e:
            err_str = str(e)
            if "L2" in err_str or "Credentials" in err_str:
                _result("Wallet balance (L2)", False, f"Auth error: {err_str}")
            else:
                _result("Wallet balance (L2)", False, err_str)
    else:
        _skip("API key derivation (L1)", "No ClobClient — PK not configured")
        _skip("Builder auth", "No ClobClient")
        _skip("Wallet balance (L2)", "No ClobClient")

    # 1f: Account address
    if clob._account:
        _result("Account address", True, f"{clob._account.address}")
    else:
        _skip("Account address", "No private key")


async def test_market_detection():
    """Test 2: Market detection from Gamma API."""
    print("\n[TEST 2] Market Detection")
    print("-" * 50)

    try:
        markets = await fetch_all_active_markets(limit=5)
        _result("Fetch active markets", True, f"{len(markets)} markets fetched")
        for m in markets[:3]:
            print(
                f"    • {m.question[:60]}... YES={m.yes_price:.2f} vol=${m.volume:,.0f}"
            )
    except Exception as e:
        _result("Fetch active markets", False, str(e))


async def test_ai_debate():
    """Test 3: AI debate engine (Bull/Bear/Judge)."""
    print("\n[TEST 3] AI Debate Engine")
    print("-" * 50)

    if not settings.GROQ_API_KEY and not settings.ANTHROPIC_API_KEY:
        _skip("Debate engine", "No AI API keys configured")
        return

    try:
        from backend.ai.debate_engine import run_debate

        result = await run_debate(
            question="Will Bitcoin exceed $90,000 by end of April 2026?",
            market_price=0.45,
            volume=50000.0,
            category="crypto",
            max_rounds=1,
        )

        if result:
            _result(
                "Debate engine",
                True,
                f"Consensus: {result.consensus_probability:.2f}, "
                f"Confidence: {result.confidence:.2f}, "
                f"Rounds: {result.rounds_completed}, "
                f"Latency: {result.latency_ms:.0f}ms",
            )
            print(f"    Reasoning: {result.reasoning[:100]}...")
        else:
            _result(
                "Debate engine", False, "Returned None — both agents may have failed"
            )
    except Exception as e:
        _result("Debate engine", False, str(e))


async def test_risk_manager():
    """Test 4: Risk manager validation."""
    print("\n[TEST 4] Risk Manager Validation")
    print("-" * 50)

    rm = RiskManager()

    # 4a: Normal trade should pass
    decision = rm.validate_trade(
        size=5.0,
        current_exposure=0.0,
        bankroll=100.0,
        confidence=0.7,
        market_ticker="TEST_MARKET",
    )
    _result("Allow normal trade", decision.allowed, decision.reason)

    # 4b: Low confidence should reject
    decision = rm.validate_trade(
        size=5.0,
        current_exposure=0.0,
        bankroll=100.0,
        confidence=0.3,
    )
    _result("Reject low confidence", not decision.allowed, decision.reason)

    # 4c: Over-exposure should cap
    decision = rm.validate_trade(
        size=50.0,
        current_exposure=70.0,
        bankroll=100.0,
        confidence=0.8,
    )
    if decision.allowed:
        _result(
            "Over-exposure cap",
            decision.adjusted_size < 50.0,
            f"Adjusted ${50.0:.2f} → ${decision.adjusted_size:.2f}",
        )
    else:
        _result("Over-exposure block", True, decision.reason)

    # 4d: Drawdown check
    dd_status = rm.check_drawdown(bankroll=100.0)
    _result(
        "Drawdown check",
        True,
        f"Daily PnL: ${dd_status.daily_pnl:.2f}, Breached: {dd_status.is_breached}",
    )


async def test_order_creation_dry_run(clob: PolymarketCLOB):
    """Test 5: Signed order creation WITHOUT posting (DRY RUN)."""
    print("\n[TEST 5] Order Creation (DRY RUN — signed but NOT posted)")
    print("-" * 50)

    if not clob._clob_client or not clob._clob_client.creds:
        _skip("Order creation", "No L2 credentials available")
        return

    # First, get a real market token_id
    try:
        resp = await clob._http.get(
            f"{CLOB_HOST}/sampling-markets", params={"next_cursor": "MA=="}
        )
        resp.raise_for_status()
        data = resp.json()
        markets = data.get("data", [])
        if not markets:
            _skip("Order creation", "No markets available for token_id")
            return

        # Get the YES token_id from first market
        tokens = markets[0].get("tokens", [])
        if not tokens:
            # Try condition_id based lookup
            condition_id = markets[0].get("condition_id", "")
            _skip(
                "Order creation",
                f"No tokens in market, condition_id={condition_id[:16]}",
            )
            return

        token_id = tokens[0].get("token_id")
        if not token_id:
            _skip("Order creation", "No token_id found in market")
            return

        market_question = markets[0].get("question", "unknown")[:50]
        print(f"    Market: {market_question}...")
        print(f"    Token ID: {token_id[:30]}...")

    except Exception as e:
        _result("Fetch market for order", False, str(e))
        return

    # Create and sign the order (but DO NOT POST)
    from py_clob_client.clob_types import OrderArgs

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=0.55,
            size=1.0,
            side="BUY",
        )

        signed_order = await asyncio.to_thread(
            clob._clob_client.create_order, order_args
        )

        if signed_order:
            # DRY RUN: We created and signed the order but WILL NOT post it
            order_id_preview = getattr(signed_order, "salt", "N/A")
            order_type = type(signed_order).__name__
            _result(
                "Order creation (signed, NOT posted)",
                True,
                f"Type={order_type}, Salt={str(order_id_preview)[:20]}...",
            )
            print("    ⚠️  Order was SIGNED but NOT posted. No real order placed.")
        else:
            _result("Order creation", False, "create_order returned None")

    except Exception as e:
        err_str = str(e)
        if "insufficient" in err_str.lower() or "balance" in err_str.lower():
            _result(
                "Order creation (insufficient balance)",
                False,
                f"Expected: {err_str[:80]} (wallet needs USDC funding)",
            )
        else:
            _result("Order creation", False, err_str[:120])


async def test_settlement_flow():
    """Test 6: Settlement flow (paper mode, no real markets)."""
    print("\n[TEST 6] Settlement Flow (paper mode)")
    print("-" * 50)

    from backend.models.database import SessionLocal, Trade, BotState
    from backend.core.settlement import settle_pending_trades

    db = SessionLocal()
    try:
        pending = db.query(Trade).filter(not Trade.settled).count()
        settled = db.query(Trade).filter(Trade.settled).count()
        state = db.query(BotState).first()

        if state:
            mode = settings.TRADING_MODE
            if mode == "paper":
                bankroll = state.paper_bankroll or 0
                pnl = state.paper_pnl or 0
                trades = state.paper_trades or 0
            elif mode == "testnet":
                bankroll = state.testnet_bankroll or 0
                pnl = state.testnet_pnl or 0
                trades = state.testnet_trades or 0
            else:
                bankroll = state.bankroll or 0
                pnl = state.total_pnl or 0
                trades = state.total_trades or 0

            _result(
                "Database state",
                True,
                f"Bankroll=${bankroll:.2f}, PnL=${pnl:.2f}, Trades={trades}",
            )
            _result("Pending trades", True, f"{pending} pending, {settled} settled")
        else:
            _result("Database state", False, "No BotState row found")

        # Try settlement (will just log "no pending trades" if DB is clean)
        try:
            result = await settle_pending_trades(db)
            _result("Settlement run", True, f"Settled {len(result)} trades")
        except Exception as e:
            _result("Settlement run", False, str(e)[:100])

    finally:
        db.close()


async def test_strategy_executor_dry_run():
    """Test 7: Strategy executor end-to-end (paper mode, no real orders)."""
    print("\n[TEST 7] Strategy Executor Dry-Run (paper mode)")
    print("-" * 50)

    from backend.models.database import SessionLocal, BotState
    from backend.core.strategy_executor import execute_decision
    from backend.config import settings as s

    db = SessionLocal()
    try:
        state = db.query(BotState).first()
        if not state:
            state = BotState(is_running=True, paper_bankroll=s.INITIAL_BANKROLL)
            db.add(state)
            db.commit()

        original_mode = s.TRADING_MODE
        s.TRADING_MODE = "paper"  # Force paper mode for safety

        decision = {
            "market_ticker": "DRY_RUN_TEST_MARKET",
            "direction": "up",
            "size": 2.0,
            "entry_price": 0.55,
            "edge": 0.08,
            "confidence": 0.72,
            "token_id": None,  # No token_id = paper mode won't attempt CLOB order
            "platform": "polymarket",
            "reasoning": "Dry-run test: no real order should be placed",
            "market_type": "btc",
        }

        result = await execute_decision(decision, strategy_name="dry_run_test", db=db)

        if result:
            _result(
                "Strategy executor (paper)",
                True,
                f"Trade created: {result['direction']} {result['market_ticker']} "
                f"${result['size']:.2f} @ {result['fill_price']:.3f}, "
                f"mode={result['trading_mode']}",
            )
            # Clean up the test trade
            from backend.models.database import Trade, Signal

            trade = db.query(Trade).filter(Trade.id == result["id"]).first()
            if trade:
                db.delete(trade)
            signal = (
                db.query(Signal)
                .filter(Signal.market_ticker == "DRY_RUN_TEST_MARKET")
                .first()
            )
            if signal:
                db.delete(signal)
            db.commit()
            _result("Test trade cleaned up", True, "")
        else:
            _result(
                "Strategy executor (paper)", False, "execute_decision returned None"
            )

        s.TRADING_MODE = original_mode

    except Exception as e:
        _result("Strategy executor (paper)", False, str(e)[:120])
    finally:
        db.close()


async def main():
    print("=" * 70)
    print("  POLYEDGE MAINNET DRY-RUN VERIFICATION")
    print(
        f"  Mode: {settings.TRADING_MODE} | Time: {datetime.now(timezone.utc).isoformat()}"
    )
    print(f"  CLOB: {CLOB_HOST} | Chain: {CHAIN_ID}")
    print("=" * 70)
    print()
    print("  ⚠️  This script exercises ALL subsystems against REAL mainnet data.")
    print("  ⚠️  Order creation SINGS an order but DOES NOT post it.")
    print("  ⚠️  No real money is at risk. Safe to run with production credentials.")
    print()

    # Initialize CLOB client
    pk = settings.POLYMARKET_PRIVATE_KEY
    async with PolymarketCLOB(
        private_key=pk,
        mode=settings.TRADING_MODE,
        builder_api_key=settings.POLYMARKET_BUILDER_API_KEY,
        builder_secret=settings.POLYMARKET_BUILDER_SECRET,
        builder_passphrase=settings.POLYMARKET_BUILDER_PASSPHRASE,
        signature_type=settings.POLYMARKET_SIGNATURE_TYPE,
    ) as clob:
        await test_clob_connectivity(clob)

    await test_market_detection()
    await test_ai_debate()
    await test_risk_manager()

    # For order creation test, use the same clob context so L2 creds are available
    async with PolymarketCLOB(
        private_key=pk,
        mode=settings.TRADING_MODE,
        builder_api_key=settings.POLYMARKET_BUILDER_API_KEY,
        builder_secret=settings.POLYMARKET_BUILDER_SECRET,
        builder_passphrase=settings.POLYMARKET_BUILDER_PASSPHRASE,
        signature_type=settings.POLYMARKET_SIGNATURE_TYPE,
    ) as clob2:
        # Derive L2 creds first
        await clob2.create_or_derive_api_creds()
        await test_order_creation_dry_run(clob2)

    await test_settlement_flow()
    await test_strategy_executor_dry_run()

    print()
    print("=" * 70)
    print("  DRY-RUN COMPLETE")
    print(f"  ✓ Passed: {PASSED}  ✗ Failed: {FAILED}  ~ Skipped: {SKIPPED}")
    print("=" * 70)

    if FAILED > 0:
        print("\n  ⚠️  Some tests failed. Review failures above before going live.")
        sys.exit(1)
    else:
        print("\n  ✓  All tests passed. System is ready for testnet mode.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
