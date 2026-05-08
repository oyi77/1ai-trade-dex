import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, AuditLog, Trade, BotState
from backend.models.audit_logger import log_trade_created, log_settlement_completed


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    state = BotState(mode="paper", paper_bankroll=1000.0, is_running=True)
    session.add(state)
    session.commit()

    yield session
    session.close()


@pytest.mark.asyncio
async def test_trade_creation_logs_audit_event(test_db):
    from backend.core.strategy_executor import execute_decision
    from backend.core.mode_context import register_context, ModeExecutionContext
    from backend.core.risk_manager import RiskManager
    from unittest.mock import AsyncMock

    # Register execution context for paper mode
    register_context(
        "paper",
        ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=RiskManager(),
            strategy_configs={},
        ),
    )

    decision = {
        "market_ticker": "BTC-UP-5M",
        "direction": "up",
        "size": 5.0,
        "entry_price": 0.65,
        "edge": 0.15,
        "confidence": 0.75,
        "model_probability": 0.80,
        "platform": "polymarket",
        "reasoning": "Test trade",
        "market_type": "btc",
    }

    result = await execute_decision(
        decision=decision,
        strategy_name="test_strategy",
        mode="paper",
        db=test_db,
    )

    assert result is not None

    audit_entries = test_db.query(AuditLog).filter(
        AuditLog.event_type == "TRADE_CREATED"
    ).all()

    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry.entity_type == "TRADE"
    assert entry.entity_id == str(result["id"])
    assert entry.new_value["market_ticker"] == "BTC-UP-5M"
    assert entry.new_value["size"] == 5.0
    assert entry.user_id == "strategy:test_strategy"


@pytest.mark.asyncio
async def test_settlement_logs_audit_event(test_db):
    trade = Trade(
        market_ticker="BTC-UP-5M",
        platform="polymarket",
        direction="up",
        entry_price=0.65,
        size=5.0,
        model_probability=0.75,
        market_price_at_entry=0.65,
        edge_at_entry=0.10,
        trading_mode="paper",
        settled=False,
    )
    test_db.add(trade)
    test_db.commit()

    trade.settled = True
    trade.result = "win"
    trade.pnl = 35.0
    trade.settlement_time = datetime.now(timezone.utc)

    log_settlement_completed(
        db=test_db,
        trade_id=trade.id,
        old_state={"settled": False, "result": "pending", "pnl": None},
        new_state={
            "settled": True,
            "result": "win",
            "pnl": 35.0,
            "settlement_time": trade.settlement_time.isoformat(),
        },
        user_id="system:settlement",
    )
    test_db.commit()

    audit_entries = test_db.query(AuditLog).filter(
        AuditLog.event_type == "SETTLEMENT_COMPLETED"
    ).all()

    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry.entity_type == "TRADE"
    assert entry.entity_id == str(trade.id)
    assert entry.old_value["settled"] is False
    assert entry.new_value["settled"] is True
    assert entry.new_value["pnl"] == 35.0


def test_audit_log_tracks_all_modes(test_db):
    for mode in ["paper", "testnet", "live"]:
        log_trade_created(
            db=test_db,
            trade_id=1,
            trade_data={"trading_mode": mode, "market": "TEST"},
            user_id=f"strategy:test_{mode}",
        )

    test_db.commit()

    entries = test_db.query(AuditLog).filter(
        AuditLog.event_type == "TRADE_CREATED"
    ).all()

    assert len(entries) == 3
    modes = [e.new_value["trading_mode"] for e in entries]
    assert set(modes) == {"paper", "testnet", "live"}


def test_audit_log_chronological_order(test_db):
    import time

    for i in range(5):
        log_trade_created(
            db=test_db,
            trade_id=i,
            trade_data={"sequence": i},
            user_id="system",
        )
        time.sleep(0.01)

    test_db.commit()

    entries = test_db.query(AuditLog).order_by(AuditLog.timestamp).all()

    assert len(entries) == 5
    for i, entry in enumerate(entries):
        assert entry.new_value["sequence"] == i
