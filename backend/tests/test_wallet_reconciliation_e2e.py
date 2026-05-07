"""
End-to-end integration tests for wallet reconciliation logic.

Tests the complete sync flow:
1. Database recovery from empty via sync_wallet
2. External trade detection (auto import)
3. Settlement verification mapping (detecting external closures & calculating PnL)
4. Orphan detection (position missing on CLOB is marked as orphaned)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Trade
from backend.core.wallet_reconciliation import WalletReconciler
from backend.data.polymarket_clob import PolymarketCLOB


# ---------------------------------------------------------------------------
# In-memory SQLite fixture (per-test isolation)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """Provide a fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def mock_clob():
    """Mock PolymarketCLOB client with builder_address set."""
    clob = MagicMock(spec=PolymarketCLOB)
    clob.builder_address = "0xTEST_WALLET_ADDRESS"
    clob.get_wallet_trades = AsyncMock(return_value=[])
    clob.get_trader_positions = AsyncMock(return_value=[])
    return clob


# ---------------------------------------------------------------------------
# Test 1: Database Recovery from Empty (Import Historical Trades)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_recovery_from_empty(db, mock_clob):
    """
    Scenario: Empty database, blockchain has 3 historical positions.
    Expected: All 3 positions imported with source='external'.
    """
    # Mock Data API response with 3 positions
    mock_positions = [
        {
            "asset": "btc-up-5m",
            "outcome": "Yes",
            "initialValue": 100.0,
            "avgPrice": 0.65,
            "redeemable": False,
        },
        {
            "asset": "eth-down-1h",
            "outcome": "No",
            "initialValue": 50.0,
            "avgPrice": 0.40,
            "redeemable": False,
        },
        {
            "asset": "sol-up-daily",
            "outcome": "Yes",
            "initialValue": 200.0,
            "avgPrice": 0.55,
            "redeemable": False,
        },
    ]

    with patch("backend.core.wallet_reconciliation.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = mock_positions
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        reconciler = WalletReconciler(clob_client=mock_clob, db=db, mode="testnet")
        imported_count = await reconciler.import_blockchain_history(max_pages=1)

        # Verify: 3 trades imported
        assert imported_count == 3

        # Verify: All trades in DB with correct attributes
        trades = db.query(Trade).all()
        assert len(trades) == 3

        # Check first trade
        trade1 = db.query(Trade).filter(Trade.market_ticker == "btc-up-5m").first()
        assert trade1 is not None
        assert trade1.direction == "up"  # Yes -> up
        assert trade1.entry_price == 0.65
        assert trade1.size == 100.0
        assert trade1.source == "external"
        assert trade1.blockchain_verified is True
        # Mock has redeemable=False, so settlement_source stays None (set only when is_redeemable=True)
        assert trade1.settlement_source is None
        assert trade1.external_import_at is not None

        # Check second trade (No -> down)
        trade2 = db.query(Trade).filter(Trade.market_ticker == "eth-down-1h").first()
        assert trade2 is not None
        assert trade2.direction == "down"  # No -> down
        assert trade2.entry_price == 0.40
        assert trade2.size == 50.0


# ---------------------------------------------------------------------------
# Test 2: External Trade Detection (Deduplication)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_trade_deduplication(db, mock_clob):
    """
    Scenario: DB has 1 trade, blockchain returns same trade + 1 new trade.
    Expected: Only the new trade is imported (no duplicates).
    """
    # Seed DB with existing trade
    existing_trade = Trade(
        market_ticker="btc-up-5m",
        platform="polymarket",
        direction="up",
        entry_price=0.65,
        size=100.0,
        timestamp=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
        trading_mode="testnet",
        source="external",
        blockchain_verified=True,
        settlement_source="data_api",
        model_probability=0.5,
        market_price_at_entry=0.65,
        edge_at_entry=0.0,
    )
    db.add(existing_trade)
    db.commit()

    # Mock Data API: same position + new position
    mock_positions = [
        {
            "asset": "btc-up-5m",  # Duplicate
            "outcome": "Yes",
            "initialValue": 100.0,
            "avgPrice": 0.65,
            "redeemable": False,
        },
        {
            "asset": "eth-down-1h",  # New
            "outcome": "No",
            "initialValue": 75.0,
            "avgPrice": 0.30,
            "redeemable": False,
        },
    ]

    with patch("backend.core.wallet_reconciliation.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = mock_positions
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        reconciler = WalletReconciler(clob_client=mock_clob, db=db, mode="testnet")
        imported_count = await reconciler.import_blockchain_history(max_pages=1)

        # Verify: Only 1 new trade imported
        assert imported_count == 1

        # Verify: Total 2 trades in DB
        trades = db.query(Trade).all()
        assert len(trades) == 2

        # Verify: New trade exists
        new_trade = db.query(Trade).filter(Trade.market_ticker == "eth-down-1h").first()
        assert new_trade is not None
        assert new_trade.direction == "down"


# ---------------------------------------------------------------------------
# Test 3: Settlement Verification (Detecting External Closures)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settlement_verification_external_closure(db, mock_clob):
    """
    Scenario: DB has 2 open trades, blockchain shows only 1 still open.
    Expected: The missing trade is marked as closed with settlement_source='data_api'.
    """
    # Seed DB with 2 open trades
    trade1 = Trade(
        market_ticker="btc-up-5m",
        platform="polymarket",
        direction="up",
        entry_price=0.65,
        size=100.0,
        timestamp=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
        trading_mode="testnet",
        source="bot",
        settled=False,
        settlement_time=None,
        model_probability=0.7,
        market_price_at_entry=0.65,
        edge_at_entry=0.05,
    )
    trade2 = Trade(
        market_ticker="eth-down-1h",
        platform="polymarket",
        direction="down",
        entry_price=0.40,
        size=50.0,
        timestamp=datetime(2026, 4, 2, 14, 30, 0, tzinfo=timezone.utc),
        trading_mode="testnet",
        source="bot",
        settled=False,
        settlement_time=None,
        model_probability=0.6,
        market_price_at_entry=0.40,
        edge_at_entry=0.10,
    )
    db.add_all([trade1, trade2])
    db.commit()

    # Mock Data API: only btc-up-5m still open
    mock_positions = [
        {
            "asset": "btc-up-5m",
            "outcome": "Yes",
            "initialValue": 100.0,
            "avgPrice": 0.65,
            "redeemable": False,
        }
    ]

    with patch("backend.core.wallet_reconciliation.httpx.AsyncClient") as mock_client_class, \
         patch("backend.core.settlement_helpers.fetch_resolution_for_trade",
               new=AsyncMock(return_value=(True, 0.0))):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = mock_positions
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        reconciler = WalletReconciler(clob_client=mock_clob, db=db, mode="testnet")
        result = await reconciler.sync_current_positions()

        # Verify: 1 updated, 1 closed
        assert result.updated_count == 1
        assert result.closed_count == 1

        # Verify: btc-up-5m still open
        trade1_updated = db.query(Trade).filter(Trade.market_ticker == "btc-up-5m").first()
        assert trade1_updated.settled is False
        assert trade1_updated.last_sync_at is not None
        assert trade1_updated.blockchain_verified is True

        # Verify: eth-down-1h marked as closed
        trade2_closed = db.query(Trade).filter(Trade.market_ticker == "eth-down-1h").first()
        assert trade2_closed.settled is True
        assert trade2_closed.settlement_time is not None
        assert trade2_closed.settlement_source == "data_api"
        assert trade2_closed.blockchain_verified is True
        assert trade2_closed.result == "win"
        assert trade2_closed.pnl == pytest.approx(30.0)  # (1.0 - 0.40) * 50


# ---------------------------------------------------------------------------
# Test 4: Orphan Detection (Position on Blockchain but Missing in DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_detection(db, mock_clob):
    """
    Scenario: Blockchain has 2 open positions, DB has only 1.
    Expected: The missing position is detected as orphaned.
    """
    # Seed DB with 1 open trade
    trade1 = Trade(
        market_ticker="btc-up-5m",
        platform="polymarket",
        direction="up",
        entry_price=0.65,
        size=100.0,
        timestamp=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
        trading_mode="testnet",
        source="bot",
        settled=False,
        model_probability=0.7,
        market_price_at_entry=0.65,
        edge_at_entry=0.05,
    )
    db.add(trade1)
    db.commit()

    # Mock Data API: 2 open positions (btc-up-5m + sol-up-daily orphaned)
    mock_positions = [
        {
            "asset": "btc-up-5m",
            "outcome": "Yes",
            "initialValue": 100.0,
            "avgPrice": 0.65,
            "redeemable": False,
        },
        {
            "asset": "sol-up-daily",  # Orphaned
            "outcome": "No",
            "initialValue": 150.0,
            "avgPrice": 0.50,
            "redeemable": False,
        },
    ]

    with patch("backend.core.wallet_reconciliation.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = mock_positions
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        reconciler = WalletReconciler(clob_client=mock_clob, db=db, mode="testnet")
        orphans = await reconciler.detect_orphaned_positions()

        # Verify: 1 orphan detected
        assert len(orphans) == 1
        assert orphans[0].market_id == "sol-up-daily"
        assert orphans[0].blockchain_size == 150.0
        assert orphans[0].blockchain_entry_price == 0.50


# ---------------------------------------------------------------------------
# Test 5: Full Reconciliation E2E Flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_reconciliation_e2e(db, mock_clob):
    """
    Scenario: Complete reconciliation cycle with:
    - 2 historical positions to import
    - 1 open position to sync
    - 1 orphaned position to create
    Expected: All operations succeed, metrics correct.
    """
    # Mock Data API response with 2 positions to import + 1 orphaned
    mock_positions = [
        {
            "asset": "btc-up-5m",
            "outcome": "Yes",
            "initialValue": 100.0,
            "avgPrice": 0.65,
            "redeemable": False,
        },
        {
            "asset": "eth-down-1h",
            "outcome": "No",
            "initialValue": 50.0,
            "avgPrice": 0.40,
            "redeemable": False,
        },
        {
            "asset": "sol-up-daily",  # Orphaned
            "outcome": "No",
            "initialValue": 150.0,
            "avgPrice": 0.50,
            "redeemable": False,
        },
    ]

    with patch("backend.core.wallet_reconciliation.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = mock_positions
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        reconciler = WalletReconciler(clob_client=mock_clob, db=db, mode="testnet")
        result = await reconciler.full_reconciliation()

        # Verify: Metrics correct
        assert result.imported_count == 3
        assert result.updated_count == 3
        assert result.closed_count == 0
        assert len(result.errors) == 0
        assert result.last_sync_at is not None

        # Verify: DB state - 3 imported positions (all are in the Data API response)
        trades = db.query(Trade).all()
        assert len(trades) == 3

        # Verify: All 3 positions imported
        btc_trade = db.query(Trade).filter(Trade.market_ticker == "btc-up-5m").first()
        assert btc_trade is not None
        assert btc_trade.source == "external"
        
        eth_trade = db.query(Trade).filter(Trade.market_ticker == "eth-down-1h").first()
        assert eth_trade is not None
        assert eth_trade.source == "external"
        
        sol_trade = db.query(Trade).filter(Trade.market_ticker == "sol-up-daily").first()
        assert sol_trade is not None
        assert sol_trade.source == "external"
