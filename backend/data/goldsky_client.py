"""Goldsky GraphQL client for ingesting historical Polymarket order-filled events."""

import json
from pathlib import Path
from typing import Optional

import httpx

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError

from loguru import logger

goldsky_breaker = CircuitBreaker(
    "goldsky_api", failure_threshold=3, recovery_timeout=120.0
)

GOLDSKY_URL = settings.GOLDSKY_API_URL
_HERE = Path(__file__).resolve().parent
CURSOR_FILE = _HERE / "goldsky_cursor.json"
BATCH_SIZE = 1000

# Platform wallets to exclude from trader analytics
PLATFORM_WALLETS = {
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
}

_GRAPHQL_QUERY = """
query OrderFilledEvents($afterTimestamp: BigInt!, $afterId: String!, $batchSize: Int!) {
  orderFilledEvents(
    first: $batchSize
    orderBy: timestamp
    orderDirection: asc
    where: {
      timestamp_gte: $afterTimestamp
      id_gt: $afterId
    }
  ) {
    id
    timestamp
    maker
    makerAssetId
    makerAmountFilled
    taker
    takerAssetId
    takerAmountFilled
    transactionHash
  }
}
"""


async def fetch_order_filled_events(
    after_timestamp: int = 0,
    after_id: str = "",
    batch_size: int = BATCH_SIZE,
) -> list[dict]:
    """Fetch a batch of orderFilledEvents from the Goldsky subgraph.

    Supports sticky-cursor pagination: when many events share the same timestamp,
    pass after_id to paginate forward within that timestamp bucket.
    """

    async def _fetch_goldsky() -> list[dict]:
        variables = {
            "afterTimestamp": str(after_timestamp),
            "afterId": after_id,
            "batchSize": batch_size,
        }
        payload = {"query": _GRAPHQL_QUERY, "variables": variables}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(GOLDSKY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if "errors" in data:
            logger.error("Goldsky GraphQL errors: %s", data["errors"])
            return []

        events = data.get("data", {}).get("orderFilledEvents", [])
        logger.debug(
            "Fetched %d orderFilledEvents (after_ts=%d, after_id=%s)",
            len(events),
            after_timestamp,
            after_id,
        )
        return events

    try:
        return await goldsky_breaker.call(_fetch_goldsky)
    except CircuitOpenError:
        logger.warning("[goldsky] Goldsky API circuit open, skipping")
        return []
    except Exception as e:
        logger.error("[goldsky] Fetch failed: %s", e)
        return []


def save_cursor(timestamp: int, event_id: str) -> None:
    """Persist ingestion cursor to disk."""
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    cursor = {"timestamp": timestamp, "event_id": event_id}
    CURSOR_FILE.write_text(json.dumps(cursor))
    logger.debug("Saved cursor: ts=%d id=%s", timestamp, event_id)


def load_cursor() -> tuple[int, str]:
    """Load ingestion cursor from disk. Returns (0, '') if not found."""
    if not CURSOR_FILE.exists():
        return 0, ""
    try:
        cursor = json.loads(CURSOR_FILE.read_text())
        return int(cursor.get("timestamp", 0)), cursor.get("event_id", "")
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Failed to load cursor (%s); starting from beginning", exc)
        return 0, ""


def process_trade_event(event: dict) -> Optional[dict]:
    """Normalise a raw orderFilledEvent into a structured trade record.

    Returns None for platform-wallet events or events that cannot be parsed.
    """
    maker = (event.get("maker") or "").lower()
    taker = (event.get("taker") or "").lower()

    if maker in PLATFORM_WALLETS or taker in PLATFORM_WALLETS:
        return None

    maker_asset_id = event.get("makerAssetId", "")
    taker_asset_id = event.get("takerAssetId", "")

    try:
        maker_amount_raw = int(event.get("makerAmountFilled", 0))
        taker_amount_raw = int(event.get("takerAmountFilled", 0))
    except (TypeError, ValueError) as exc:
        logger.warning("Could not parse amounts in event %s: %s", event.get("id"), exc)
        return None

    # Identify USDC side (assetId == "0") and token side
    if maker_asset_id == "0":
        usdc_amount_raw = maker_amount_raw
        token_amount_raw = taker_amount_raw
        market_token_id = taker_asset_id
        maker_direction = "BUY"
        taker_direction = "SELL"
    else:
        usdc_amount_raw = taker_amount_raw
        token_amount_raw = maker_amount_raw
        market_token_id = maker_asset_id
        maker_direction = "SELL"
        taker_direction = "BUY"

    if token_amount_raw == 0:
        return None

    # Normalise USDC amounts (6 decimals)
    usd_amount = usdc_amount_raw / 1_000_000
    token_amount = token_amount_raw / 1_000_000
    price = usd_amount / token_amount

    return {
        "timestamp": int(event.get("timestamp", 0)),
        "maker": maker,
        "taker": taker,
        "market_token_id": market_token_id,
        "maker_direction": maker_direction,
        "taker_direction": taker_direction,
        "price": price,
        "usd_amount": usd_amount,
        "token_amount": token_amount,
        "tx_hash": event.get("transactionHash", ""),
    }


def _process_trade_events(events: list[dict]) -> list[dict]:
    """Process a list of raw events and return only valid trade records."""
    results = []
    for event in events:
        record = process_trade_event(event)
        if record is not None:
            results.append(record)
    return results


async def ingest_historical_trades(max_batches: int = 100) -> int:
    """Ingest historical trades from Goldsky using cursor-based pagination.

    Returns the total number of raw events processed (including skipped platform events).
    """
    after_timestamp, after_id = load_cursor()
    total_processed = 0
    all_records: list[dict] = []

    for batch_num in range(max_batches):
        logger.info(
            "Fetching batch %d/%d (ts=%d, id=%s)",
            batch_num + 1,
            max_batches,
            after_timestamp,
            after_id,
        )

        events = await fetch_order_filled_events(
            after_timestamp=after_timestamp,
            after_id=after_id,
            batch_size=BATCH_SIZE,
        )

        if not events:
            logger.info(
                "No more events — ingestion complete after %d batches", batch_num + 1
            )
            break

        records = _process_trade_events(events)
        all_records.extend(records)
        total_processed += len(events)

        last_event = events[-1]
        last_ts = int(last_event.get("timestamp", after_timestamp))
        last_id = last_event.get("id", "")

        # Sticky-cursor: if all events share the same timestamp, advance by id_gt only
        all_same_ts = all(int(e.get("timestamp", 0)) == last_ts for e in events)
        if all_same_ts:
            after_id = last_id
            after_timestamp = last_ts
        else:
            after_timestamp = last_ts
            after_id = ""

        save_cursor(after_timestamp, after_id)

        if len(events) < BATCH_SIZE:
            logger.info(
                "Partial batch — ingestion complete (%d events)", total_processed
            )
            break

    logger.info(
        "Ingestion finished: %d total events, %d valid records",
        total_processed,
        len(all_records),
    )
    return all_records
