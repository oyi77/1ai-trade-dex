"""Tests for backend/data/goldsky_client.py."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.data.goldsky_client import (
    PLATFORM_WALLETS,
    fetch_order_filled_events,
    ingest_historical_trades,
    load_cursor,
    process_trade_event,
    save_cursor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    *,
    event_id: str = "evt-1",
    timestamp: int = 1700000000,
    maker: str = "0xaaaa",
    taker: str = "0xbbbb",
    maker_asset_id: str = "0",
    taker_asset_id: str = "0xtoken123",
    maker_amount: int = 10_000_000,   # 10 USDC in raw units
    taker_amount: int = 20_000_000,   # 20 tokens in raw units
    tx_hash: str = "0xhash",
) -> dict:
    return {
        "id": event_id,
        "timestamp": str(timestamp),
        "maker": maker,
        "taker": taker,
        "makerAssetId": maker_asset_id,
        "takerAssetId": taker_asset_id,
        "makerAmountFilled": str(maker_amount),
        "takerAmountFilled": str(taker_amount),
        "transactionHash": tx_hash,
    }


# ---------------------------------------------------------------------------
# 1. Maker buys: makerAssetId == "0"
# ---------------------------------------------------------------------------

def test_process_trade_event_buy():
    """When makerAssetId is '0', maker is the buyer (USDC -> token)."""
    event = _make_event(
        maker_asset_id="0",
        taker_asset_id="0xtoken456",
        maker_amount=50_000_000,   # 50 USDC
        taker_amount=100_000_000,  # 100 tokens
    )
    result = process_trade_event(event)

    assert result is not None
    assert result["maker_direction"] == "BUY"
    assert result["taker_direction"] == "SELL"
    assert result["market_token_id"] == "0xtoken456"
    assert result["usd_amount"] == pytest.approx(50.0)
    assert result["token_amount"] == pytest.approx(100.0)
    assert result["price"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 2. Maker sells: takerAssetId == "0"
# ---------------------------------------------------------------------------

def test_process_trade_event_sell():
    """When takerAssetId is '0', maker is the seller (token -> USDC)."""
    event = _make_event(
        maker_asset_id="0xtoken789",
        taker_asset_id="0",
        maker_amount=200_000_000,  # 200 tokens
        taker_amount=80_000_000,   # 80 USDC
    )
    result = process_trade_event(event)

    assert result is not None
    assert result["maker_direction"] == "SELL"
    assert result["taker_direction"] == "BUY"
    assert result["market_token_id"] == "0xtoken789"
    assert result["usd_amount"] == pytest.approx(80.0)
    assert result["token_amount"] == pytest.approx(200.0)
    assert result["price"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# 3. Platform wallet exclusion
# ---------------------------------------------------------------------------

def test_platform_wallet_excluded():
    """Events involving platform wallets must return None."""
    platform_wallet = next(iter(PLATFORM_WALLETS))

    # Maker is a platform wallet
    event_maker = _make_event(maker=platform_wallet)
    assert process_trade_event(event_maker) is None

    # Taker is a platform wallet
    event_taker = _make_event(taker=platform_wallet)
    assert process_trade_event(event_taker) is None

    # Neither is a platform wallet — should succeed
    event_ok = _make_event(maker="0xuser1", taker="0xuser2")
    assert process_trade_event(event_ok) is not None


# ---------------------------------------------------------------------------
# 4. Cursor round-trip persistence
# ---------------------------------------------------------------------------

def test_save_and_load_cursor(tmp_path: Path, monkeypatch):
    """Cursor saved via save_cursor() must be retrievable via load_cursor()."""
    cursor_file = tmp_path / "goldsky_cursor.json"
    monkeypatch.setattr("backend.data.goldsky_client.CURSOR_FILE", cursor_file)

    ts = 1700000999
    eid = "0xabcdef"
    save_cursor(ts, eid)

    loaded_ts, loaded_id = load_cursor()
    assert loaded_ts == ts
    assert loaded_id == eid


def test_load_cursor_missing(tmp_path: Path, monkeypatch):
    """load_cursor() returns (0, '') when no cursor file exists."""
    cursor_file = tmp_path / "nonexistent_cursor.json"
    monkeypatch.setattr("backend.data.goldsky_client.CURSOR_FILE", cursor_file)

    ts, eid = load_cursor()
    assert ts == 0
    assert eid == ""


# ---------------------------------------------------------------------------
# 5. Sticky-cursor logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sticky_cursor_logic(tmp_path: Path, monkeypatch):
    """When all events in a batch share the same timestamp, the cursor should
    advance by id_gt without moving the timestamp forward."""
    cursor_file = tmp_path / "goldsky_cursor.json"
    monkeypatch.setattr("backend.data.goldsky_client.CURSOR_FILE", cursor_file)
    monkeypatch.setattr("backend.data.goldsky_client.BATCH_SIZE", 2)

    shared_ts = 1700000000

    # First batch: two events with the same timestamp (full batch)
    batch1 = [
        _make_event(event_id="id-1", timestamp=shared_ts, maker_amount=10_000_000, taker_amount=20_000_000),
        _make_event(event_id="id-2", timestamp=shared_ts, maker_amount=10_000_000, taker_amount=20_000_000),
    ]
    # Second batch: empty — signals end of data
    batch2: list[dict] = []

    call_count = 0

    async def mock_fetch(after_timestamp, after_id, batch_size):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return batch1
        return batch2

    monkeypatch.setattr("backend.data.goldsky_client.fetch_order_filled_events", mock_fetch)

    total = await ingest_historical_trades(max_batches=5)

    assert len(total) == 2  # only first batch counted (returns list of records)

    # After sticky batch the cursor timestamp must stay the same; id advances
    saved_ts, saved_id = load_cursor()
    assert saved_ts == shared_ts   # timestamp NOT moved forward
    assert saved_id == "id-2"      # id advanced to last event id


# ---------------------------------------------------------------------------
# 6. USDC amount normalisation (10^6 division)
# ---------------------------------------------------------------------------

def test_normalize_amounts():
    """Raw amounts must be divided by 1_000_000 for USDC normalisation."""
    raw_usdc = 5_000_000   # should become 5.0
    raw_tokens = 10_000_000  # should become 10.0

    event = _make_event(
        maker_asset_id="0",
        taker_asset_id="0xtok",
        maker_amount=raw_usdc,
        taker_amount=raw_tokens,
    )
    result = process_trade_event(event)

    assert result is not None
    assert result["usd_amount"] == pytest.approx(5.0)
    assert result["token_amount"] == pytest.approx(10.0)
    assert result["price"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 7. fetch_order_filled_events — mocked HTTP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_order_filled_events_success():
    """fetch_order_filled_events should return the events list from the response."""
    fake_events = [_make_event(event_id="x1")]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"data": {"orderFilledEvents": fake_events}})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("backend.data.goldsky_client.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_order_filled_events(after_timestamp=0, after_id="", batch_size=10)

    assert result == fake_events


@pytest.mark.asyncio
async def test_fetch_order_filled_events_graphql_errors():
    """GraphQL errors in the response should return an empty list."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"errors": [{"message": "bad query"}]})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("backend.data.goldsky_client.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_order_filled_events()

    assert result == []
