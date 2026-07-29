"""Helper utilities for scheduling strategies."""

from contextlib import asynccontextmanager

from loguru import logger

from backend.config import settings


@asynccontextmanager
async def _market_data_clob(mode: str):
    """Read-only PolymarketCLOB for strategy market data (order books,
    mid prices). Yields None if the client cannot be constructed so a CLOB
    outage degrades strategies to their no-clob fallbacks instead of
    failing the whole cycle.
    """
    from backend.data.polymarket_clob import clob_from_settings

    clob = None
    try:
        clob = clob_from_settings(mode)
        await clob.__aenter__()
    except Exception as e:
        logger.warning(f"[scheduler] CLOB client unavailable for {mode}: {e}")
        clob = None
    try:
        yield clob
    finally:
        if clob is not None:
            await clob.__aexit__(None, None, None)


def _get_bankroll_for_mode(state, mode: str) -> float:
    """Read the correct bankroll field based on trading mode."""
    if mode == "paper":
        return (
            state.paper_bankroll
            if state.paper_bankroll is not None
            else settings.INITIAL_BANKROLL
        )
    elif mode == "testnet":
        return (
            state.testnet_bankroll
            if state.testnet_bankroll is not None
            else settings.INITIAL_BANKROLL
        )
    else:
        return (
            state.bankroll if state.bankroll is not None else settings.INITIAL_BANKROLL
        )
