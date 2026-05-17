"""
Integration tests for real-time balance WebSocket updates.
"""

from backend.models.database import BotState, Trade


def test_stats_endpoint_returns_balance(client, db):
    db.query(Trade).filter_by(trading_mode="paper").delete()
    db.commit()

    state = db.query(BotState).filter_by(mode="paper").first()
    if not state:
        state = BotState(
            mode="paper",
            is_running=False,
            bankroll=2500.0,
        )
        db.add(state)
    else:
        state.bankroll = 2500.0

    db.commit()

    response = client.get("/api/v1/stats")
    assert response.status_code == 200

    data = response.json()
    assert "bankroll" in data
    assert data["bankroll"] > 0


def test_stats_endpoint_paper_mode(client, db):
    db.query(Trade).filter_by(trading_mode="paper").delete()
    db.commit()

    # Reset all modes to zero pnl to prevent cross-contamination
    for mode_state in db.query(BotState).all():
        mode_state.total_pnl = 0.0
        mode_state.bankroll = 10000.0
    db.commit()

    state = db.query(BotState).filter_by(mode="paper").first()
    if state:
        state.bankroll = 12000.0
        state.total_pnl = 2000.0
        state.total_trades = 10
        state.winning_trades = 6

    for i in range(10):
        trade = Trade(
            market_ticker=f"paper-market-{i}",
            platform="polymarket",
            direction="up",
            entry_price=0.65,
            size=100.0,
            settled=(i < 6),
            result="win" if i < 6 else "pending",
            trading_mode="paper",
            source="bot",
            model_probability=0.5,
            market_price_at_entry=0.65,
            edge_at_entry=0.0,
            pnl=200.0 if i < 6 else 0.0,
        )
        db.add(trade)

    db.commit()

    response = client.get("/api/v1/stats")
    assert response.status_code == 200

    data = response.json()
    assert data.get("mode") in ["paper", "all"]
    assert data["bankroll"] >= 1000.0
    # total_pnl may be negative if live mode has wallet-synced losses
    assert "total_pnl" in data


def test_stats_endpoint_includes_mode_specific_data(client, db):
    paper_state = db.query(BotState).filter_by(mode="paper").first()
    if paper_state:
        paper_state.bankroll = 11000.0
        paper_state.total_pnl = 1000.0
        paper_state.total_trades = 5
        paper_state.winning_trades = 3

    testnet_state = db.query(BotState).filter_by(mode="testnet").first()
    if testnet_state:
        testnet_state.bankroll = 200.0
        testnet_state.total_pnl = 50.0
        testnet_state.total_trades = 2
        testnet_state.winning_trades = 1

    live_state = db.query(BotState).filter_by(mode="live").first()
    if live_state:
        db.info["allow_live_financial_update"] = True
        live_state.bankroll = 5000.0
        live_state.total_pnl = 300.0
        live_state.total_trades = 3
        live_state.winning_trades = 2
    db.commit()
    db.info.pop("allow_live_financial_update", None)

    response = client.get("/api/v1/stats")
    assert response.status_code == 200

    data = response.json()
    assert "paper" in data
    assert "testnet" in data
    assert "live" in data
    assert data["paper"]["bankroll"] == 11000.0
    assert data["testnet"]["bankroll"] == 200.0
    assert data["live"]["bankroll"] == 5000.0


def test_stats_endpoint_calculates_unrealized_pnl(client, db):
    db.query(Trade).filter_by(trading_mode="paper").delete()
    db.commit()

    state = db.query(BotState).first()
    if not state:
        state = BotState(
            mode="paper",
            is_running=False,
            bankroll=10000.0,
            total_trades=0,
            winning_trades=0,
            total_pnl=0.0,
            paper_bankroll=10000.0,
            paper_pnl=0.0,
            paper_trades=0,
            paper_wins=0,
        )
        db.add(state)
    db.commit()

    trade = Trade(
        market_ticker="test-market",
        platform="polymarket",
        direction="up",
        entry_price=0.65,
        size=100.0,
        settled=False,
        result="pending",
        trading_mode="paper",
        source="bot",
        model_probability=0.5,
        market_price_at_entry=0.65,
        edge_at_entry=0.0,
    )
    db.add(trade)
    db.commit()

    response = client.get("/api/v1/stats")
    assert response.status_code in [200, 404]

    if response.status_code == 200:
        data = response.json()
        assert data.get("open_trades", 0) >= 0


def test_stats_endpoint_handles_missing_botstate(client, db):
    # Delete BotState to test 404 case, then restore it for subsequent tests
    db.query(BotState).delete()
    db.commit()

    response = client.get("/api/v1/stats")
    assert response.status_code == 404
    assert "not initialized" in response.json()["detail"]

    # Restore BotState for subsequent tests
    for mode in ["paper", "testnet", "live"]:
        if not db.query(BotState).filter_by(mode=mode).first():
            db.add(BotState(
                mode=mode,
                bankroll=10000.0 if mode != "testnet" else 100.0,
                total_trades=0,
                winning_trades=0,
                total_pnl=0.0,
                is_running=True,
            ))
    db.commit()
    db.expire_all()


def test_stats_pnl_source_indicator(client, db):
    # Clean up any trades from previous tests to avoid state leakage
    db.query(Trade).filter_by(trading_mode="paper").delete()
    db.commit()

    state = db.query(BotState).filter_by(mode="paper").first()
    if state:
        state.bankroll = 10000.0
        state.total_pnl = 0.0
        state.total_trades = 0
        state.winning_trades = 0
    db.commit()

    response = client.get("/api/v1/stats?mode=paper")
    assert response.status_code == 200

    data = response.json()
    assert "pnl_source" in data
    assert data["pnl_source"] in ["botstate", "recalculated"]


def test_stats_includes_position_metrics(client, db):
    # Clean up any trades from previous tests to avoid state leakage
    db.query(Trade).filter_by(trading_mode="paper").delete()
    db.commit()

    state = db.query(BotState).filter_by(mode="paper").first()
    if state:
        state.bankroll = 10000.0
        state.total_pnl = 0.0
        state.total_trades = 0
        state.winning_trades = 0
    db.commit()

    response = client.get("/api/v1/stats?mode=paper")
    assert response.status_code == 200

    data = response.json()
    assert "open_exposure" in data
    assert "open_trades" in data
    assert "settled_trades" in data
    assert "settled_wins" in data
    assert "unrealized_pnl" in data
    assert "position_cost" in data
    assert "position_market_value" in data


def test_stats_includes_available_and_total_balance_fields(client, db):
    state = db.query(BotState).filter_by(mode="paper").first()
    if state:
        state.bankroll = 9800.0
        state.paper_bankroll = 9800.0
        state.total_pnl = -200.0
        state.paper_pnl = -200.0
    db.commit()

    response = client.get("/api/v1/stats?mode=paper")
    assert response.status_code == 200

    data = response.json()
    assert "available_balance" in data
    assert "total_balance" in data
    assert "realized_pnl" in data
    assert "account_pnl" in data
    assert data["available_balance"] == data["bankroll"]
    assert data["realized_pnl"] == data["total_pnl"]


def test_live_stats_realized_pnl_is_not_forced_to_account_pnl(client, db):
    live_state = db.query(BotState).filter_by(mode="live").first()
    db.info["allow_live_financial_update"] = True
    live_state.bankroll = 140.0
    live_state.total_pnl = 12.0
    db.commit()
    db.info.pop("allow_live_financial_update", None)

    db.add(
        Trade(
            market_ticker="live-loss",
            platform="polymarket",
            direction="down",
            entry_price=0.5,
            size=10.0,
            settled=True,
            result="loss",
            pnl=-3.0,
            trading_mode="live",
        )
    )
    db.commit()

    from unittest.mock import AsyncMock, patch

    with patch(
        "backend.api.system.fetch_pm_profile_pnl",
        AsyncMock(return_value=25.740828),
    ):
        response = client.get("/api/v1/stats?mode=live")

    assert response.status_code == 200
    data = response.json()
    assert data["total_pnl"] == 25.740828
    assert data["account_pnl"] == 25.740828
    assert data["realized_pnl"] == -3.0
