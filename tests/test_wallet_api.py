import pytest

def test_create_trading_wallet(test_app):
    from backend.api.auth import require_admin
    from backend.api.main import app
    app.dependency_overrides[require_admin] = lambda: None
    
    response = test_app.post(
        "/api/v1/wallet-allocations/wallets",
        json={
            "label": "test_wallet",
            "chain": "polymarket",
            "address": "0xabc",
            "enabled": True,
            "is_paper": False
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "test_wallet"
    assert data["address"] == "0xabc"

def test_create_wallet_allocation(test_app, db_session):
    from backend.api.auth import require_admin
    from backend.api.main import app
    app.dependency_overrides[require_admin] = lambda: None

    from backend.models.database import StrategyConfig
    strat = StrategyConfig(strategy_name="test_strategy", enabled=True, mode="paper")
    db_session.add(strat)
    
    from backend.models.trading_wallet import TradingWallet
    w = TradingWallet(label="tw", chain="poly", address="0x1")
    db_session.add(w)
    db_session.commit()
    
    response = test_app.post(
        "/api/v1/wallet-allocations/allocations",
        json={
            "wallet_id": w.id,
            "strategy_name": "test_strategy",
            "weight": 0.8,
            "enabled": True
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["strategy_name"] == "test_strategy"
    assert data["weight"] == 0.8
