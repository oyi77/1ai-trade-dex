import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from contextlib import contextmanager

from backend.models.database import Trade, StrategyConfig, BotState
from backend.core.strategy_executor import execute_decision, _maker_first_execute


@pytest.fixture(autouse=True)
def setup_bot_states(db_session):
    """Ensure BotState records exist in the DB for testing."""
    from backend.config import settings
    for mode in ["paper", "testnet", "live"]:
        state = db_session.query(BotState).filter_by(mode=mode).first()
        if not state:
            initial_bankroll = settings.INITIAL_BANKROLL if mode != "testnet" else 100.0
            db_session.add(
                BotState(
                    mode=mode,
                    bankroll=initial_bankroll,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    is_running=True,
                )
            )
    db_session.commit()


@pytest.mark.asyncio
async def test_maker_first_execute_resting_fill():
    """GTC order rests and fills — should record full maker_size."""
    clob = AsyncMock()

    maker_res = SimpleNamespace(
        success=True,
        order_id="maker-123",
        fill_price=0.55,
        fill_size=0.0,
    )
    clob.place_limit_order.return_value = maker_res

    # get_open_orders returns empty → order filled while resting
    clob.get_open_orders.return_value = []

    with patch("backend.core.strategy_executor.MAKER_WAIT_SECONDS", 0.05), \
         patch("backend.core.strategy_executor.MAKER_POLL_INTERVAL_SECONDS", 0.01):
        res = await _maker_first_execute(
            clob=clob,
            token_id="0xabc",
            side="BUY",
            price=0.55,
            size=10.0,
            strategy_name="test_strat",
            mode="live",
            market_ticker="BTC-UP",
        )

    assert res.success is True
    assert res.order_id == "maker-123"
    assert res.maker_filled is True
    assert res.maker_size == 10.0
    assert res.taker_size == 0.0


@pytest.mark.asyncio
async def test_maker_first_execute_taker_escalation():
    """GTC times out → escalated to FAK taker order."""
    clob = AsyncMock()

    maker_res = SimpleNamespace(
        success=True,
        order_id="maker-123",
        fill_price=0.55,
        fill_size=0.0,
    )
    taker_res = SimpleNamespace(
        success=True,
        order_id="taker-456",
        fill_price=0.56,
        fill_size=10.0,
    )

    # 1st: GTC resting, 2nd: FAK taker
    clob.place_limit_order.side_effect = [maker_res, taker_res]
    clob.get_open_orders.return_value = [{"id": "maker-123"}]
    clob.cancel_order.return_value = True

    with patch("backend.core.strategy_executor.MAKER_WAIT_SECONDS", 0.02), \
         patch("backend.core.strategy_executor.MAKER_POLL_INTERVAL_SECONDS", 0.01):
        res = await _maker_first_execute(
            clob=clob,
            token_id="0xabc",
            side="BUY",
            price=0.55,
            size=10.0,
            strategy_name="test_strat",
            mode="live",
            market_ticker="BTC-UP",
        )

    assert res.success is True
    assert res.order_id == "taker-456"
    assert res.maker_filled is False
    assert res.maker_size == 0.0
    assert res.taker_size == 10.0


@pytest.mark.asyncio
async def test_maker_first_execute_force_maker_only():
    """force_maker_only=True → abort rather than escalate to taker."""
    clob = AsyncMock()

    maker_res = SimpleNamespace(
        success=True,
        order_id="maker-123",
        fill_price=0.55,
        fill_size=0.0,
    )
    clob.place_limit_order.return_value = maker_res
    clob.get_open_orders.return_value = [{"id": "maker-123"}]
    clob.cancel_order.return_value = True

    with patch("backend.core.strategy_executor.MAKER_WAIT_SECONDS", 0.02), \
         patch("backend.core.strategy_executor.MAKER_POLL_INTERVAL_SECONDS", 0.01):
        res = await _maker_first_execute(
            clob=clob,
            token_id="0xabc",
            side="BUY",
            price=0.55,
            size=10.0,
            strategy_name="test_strat",
            mode="live",
            market_ticker="BTC-UP",
            force_maker_only=True,
        )

    assert res.success is False
    assert res.maker_size == 0.0
    assert res.taker_size == 0.0
    # No FAK escalation placed — only the initial GTC order
    assert clob.place_limit_order.call_count == 1


def test_spread_check_maker_classification():
    """entry_price < best_ask → classified as maker (pure unit test of classification logic)."""
    # Replicate the spread-check classification logic from _execute_decision_live_clob
    best_ask = 0.58
    entry_price = 0.55  # below best_ask → maker
    base_size = 10.0

    if entry_price >= best_ask:
        taker_size = base_size
        maker_size = 0.0
    else:
        maker_size = base_size
        taker_size = 0.0

    role = "maker" if (maker_size or 0.0) >= (taker_size or 0.0) else "taker"

    assert role == "maker"
    assert maker_size == 10.0
    assert taker_size == 0.0


def test_spread_check_taker_classification():
    """entry_price >= best_ask → classified as taker (pure unit test of classification logic)."""
    best_ask = 0.58
    entry_price = 0.59  # at or above best_ask → taker
    base_size = 10.0

    if entry_price >= best_ask:
        taker_size = base_size
        maker_size = 0.0
    else:
        maker_size = base_size
        taker_size = 0.0

    role = "maker" if (maker_size or 0.0) >= (taker_size or 0.0) else "taker"

    assert role == "taker"
    assert maker_size == 0.0
    assert taker_size == 10.0


def test_spread_check_at_best_ask_is_taker():
    """entry_price == best_ask exactly → taker (boundary condition)."""
    best_ask = 0.58
    entry_price = 0.58  # exactly at best_ask → taker
    base_size = 5.0

    if entry_price >= best_ask:
        taker_size = base_size
        maker_size = 0.0
    else:
        maker_size = base_size
        taker_size = 0.0

    role = "maker" if (maker_size or 0.0) >= (taker_size or 0.0) else "taker"

    assert role == "taker"
    assert maker_size == 0.0
    assert taker_size == 5.0


def test_maker_taker_performance_audit_throttling(db_session):
    """AGI throttling: taker-underperforming strategy gets force_maker_only injected."""
    cfg = StrategyConfig(
        strategy_name="underperforming_strat",
        enabled=True,
        trading_mode="paper",
    )
    db_session.add(cfg)
    db_session.commit()

    # Maker trades: profitable, within last 1h (to pass initial window gate)
    for i in range(3):
        db_session.add(
            Trade(
                market_ticker=f"MKT-M-{i}",
                direction="buy",
                entry_price=0.5,
                size=10.0,
                trading_mode="paper",
                strategy="underperforming_strat",
                status="closed",
                pnl=1.0,
                settled=True,
                role="maker",
                result="win",
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
        )
    # Taker trades: heavily losing, also within 1h window
    for i in range(3):
        db_session.add(
            Trade(
                market_ticker=f"MKT-T-{i}",
                direction="buy",
                entry_price=0.5,
                size=10.0,
                trading_mode="paper",
                strategy="underperforming_strat",
                status="closed",
                pnl=-3.0,
                settled=True,
                role="taker",
                result="loss",
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
        )
    db_session.commit()

    from backend.config import settings
    from backend.core.scheduling.scheduler import auto_disable_losing_strategies
    from unittest.mock import PropertyMock

    # Redirect get_db_session → test session so the function sees our test data
    @contextmanager
    def _mock_get_db_session():
        yield db_session

    # active_modes_set is a @property — must patch on the class, not instance
    with patch.object(
            type(settings), "active_modes_set",
            new_callable=PropertyMock,
            return_value={"paper"}
        ), \
        patch.object(settings, "AGI_AUTO_DISABLE_MIN_TRADES", 2), \
        patch("backend.db.utils.get_db_session", _mock_get_db_session):
        auto_disable_losing_strategies()

    db_session.refresh(cfg)
    assert cfg.rehab_allocation_pct == 0.50
    params = json.loads(cfg.params) if cfg.params else {}
    assert params.get("force_maker_only") is True
