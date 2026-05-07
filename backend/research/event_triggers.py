"""Event-driven research triggers — research fires on signals, settlements, regime changes."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict

logger = logging.getLogger("trading_bot")

_debounce: dict[str, float] = {}
DEBOUNCE_SECONDS = 300  # 5 min per market_ticker

_tick_keywords = re.compile(
    r"\b(btc|bitcoin|eth|ethereum|sol|solana|crypto|bitcoin)\b", re.I
)
_political_keywords = re.compile(
    r"\b(trump|biden|election|senate|congress|president|republican|democrat)\b", re.I
)
_weather_keywords = re.compile(
    r"\b(temperature|weather|forecast|celsius|fahrenheit|heat|cold|storm)\b", re.I
)


def _classify_market(ticker: str, title: str = "") -> list[str]:
    combined = f"{ticker} {title}".lower()
    queries: list[str] = []

    if _tick_keywords.search(combined):
        queries.extend(["bitcoin BTC price prediction", "crypto market analysis"])
    if _political_keywords.search(combined):
        queries.extend(["US politics prediction market", "election odds analysis"])
    if _weather_keywords.search(combined):
        queries.extend(["weather forecast temperature", "climate prediction markets"])

    if not queries:
        queries.append(ticker.replace("-", " ").replace("_", " "))

    return queries[:4]


def _should_run(market_key: str) -> bool:
    now = time.time()
    last = _debounce.get(market_key, 0)
    if now - last < DEBOUNCE_SECONDS:
        return False
    _debounce[market_key] = now
    return True


async def on_signal_found(event_type: str, data: Dict[str, Any]) -> None:
    market_ticker = data.get("market_ticker", "")
    if not market_ticker or not _should_run(f"signal:{market_ticker}"):
        return

    market_title = data.get("market_title", "")
    queries = _classify_market(market_ticker, market_title)

    logger.info(
        "EVENT-RESEARCH: signal_found for '%s' → queries=%s", market_ticker, queries
    )
    try:
        from backend.research.pipeline import ResearchPipeline

        pipeline = ResearchPipeline()
        items = await pipeline.run_research_cycle(markets=queries)

        if items:
            from backend.research.storage import ResearchStorage

            storage = ResearchStorage()
            stored = await storage.store_items(items)
            logger.info(
                "EVENT-RESEARCH: stored %d/%d items for signal '%s'",
                stored,
                len(items),
                market_ticker,
            )
    except Exception as exc:
        logger.warning("EVENT-RESEARCH: signal trigger failed for '%s': %s", market_ticker, exc)


async def on_trade_settled(event_type: str, data: Dict[str, Any]) -> None:
    result = data.get("result", "")
    if result != "loss":
        return

    market_ticker = data.get("market_ticker", "")
    if not market_ticker or not _should_run(f"settlement:{market_ticker}"):
        return

    pnl = data.get("pnl", 0)
    logger.info(
        "EVENT-RESEARCH: trade_settled LOSS on '%s' (pnl=%.2f) → targeted research",
        market_ticker,
        pnl,
    )
    try:
        from backend.research.pipeline import ResearchPipeline

        pipeline = ResearchPipeline()
        queries = _classify_market(market_ticker)
        items = await pipeline.run_research_cycle(markets=queries)

        if items:
            from backend.research.storage import ResearchStorage

            storage = ResearchStorage()
            stored = await storage.store_items(items)
            logger.info(
                "EVENT-RESEARCH: stored %d/%d items for settlement '%s'",
                stored,
                len(items),
                market_ticker,
            )
    except Exception as exc:
        logger.warning(
            "EVENT-RESEARCH: settlement trigger failed for '%s': %s", market_ticker, exc
        )


async def on_regime_changed(event_type: str, data: Dict[str, Any]) -> None:
    if not _should_run("regime:broad"):
        return

    regime = data.get("regime", "unknown")
    logger.info("EVENT-RESEARCH: regime_changed → '%s' → broad research", regime)
    try:
        from backend.research.pipeline import ResearchPipeline

        pipeline = ResearchPipeline()
        items = await pipeline.run_research_cycle(
            markets=["market regime change analysis", "prediction market volatility"]
        )

        if items:
            from backend.research.storage import ResearchStorage

            storage = ResearchStorage()
            stored = await storage.store_items(items)
            logger.info(
                "EVENT-RESEARCH: stored %d/%d items for regime change", stored, len(items)
            )
    except Exception as exc:
        logger.warning("EVENT-RESEARCH: regime trigger failed: %s", exc)


def register_research_triggers() -> None:
    from backend.core.event_bus import subscribe_handler

    subscribe_handler("signal_found", on_signal_found)
    subscribe_handler("trade_settled", on_trade_settled)
    subscribe_handler("regime_changed", on_regime_changed)
    logger.info(
        "EVENT-RESEARCH: registered handlers for signal_found, trade_settled, regime_changed"
    )
