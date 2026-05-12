"""Debate router with MiroFish fallback logic.

Routes debate requests to either MiroFish API or local DebateEngine based on
the `mirofish_enabled` flag in SystemSettings. Provides graceful fallback to
local debate on MiroFish failures.
"""

import time
from loguru import logger

from sqlalchemy.orm import Session

from backend.ai.debate_engine import DebateResult, SignalVote, run_debate
from backend.ai.mirofish_client import MiroFishClient, MiroFishSignal
from backend.api.settings import _get_setting


def _convert_signals_to_debate_result(
    signals: list[MiroFishSignal],
    question: str,
    market_price: float,
    latency_ms: float,
) -> DebateResult:
    """Convert MiroFish signals to DebateResult format.

    Args:
        signals: List of MiroFish prediction signals
        question: Market question
        market_price: Current market YES price
        latency_ms: API call latency in milliseconds

    Returns:
        DebateResult with consensus from MiroFish signals
    """
    if not signals:
        # Return neutral result if no signals
        return DebateResult(
            consensus_probability=market_price,
            confidence=0.0,
            reasoning="No MiroFish signals available",
            market_question=question,
            market_price=market_price,
            latency_ms=latency_ms,
            data_sources=["mirofish"],
        )

    # Convert signals to SignalVote format
    signal_votes = [
        SignalVote(
            source=sig.source,
            prediction=sig.prediction,
            confidence=sig.confidence,
            reasoning=sig.reasoning,
            weight=sig.confidence,  # Use confidence as weight
        )
        for sig in signals
    ]

    # Compute weighted consensus
    total_weight = sum(vote.weight for vote in signal_votes)
    if total_weight > 0:
        consensus = sum(
            vote.prediction * vote.weight for vote in signal_votes
        ) / total_weight
        avg_confidence = sum(
            vote.confidence * vote.weight for vote in signal_votes
        ) / total_weight
    else:
        consensus = market_price
        avg_confidence = 0.0

    # Build reasoning summary
    reasoning_parts = [
        f"MiroFish consensus from {len(signals)} signal(s):",
    ]
    for sig in signals:
        reasoning_parts.append(
            f"- {sig.source}: {sig.prediction:.3f} (conf={sig.confidence:.2f})"
        )
    reasoning = "\n".join(reasoning_parts)

    return DebateResult(
        consensus_probability=consensus,
        confidence=avg_confidence,
        reasoning=reasoning,
        market_question=question,
        market_price=market_price,
        latency_ms=latency_ms,
        data_sources=["mirofish"],
        signal_votes=signal_votes,
    )


async def run_debate_with_routing(
    db: Session,
    question: str,
    market_price: float,
    volume: float = 0.0,
    category: str = "",
    context: str = "",
    max_rounds: int = 2,
    data_sources: list[str] | None = None,
    signal_votes: list[SignalVote] | None = None,
) -> DebateResult | None:
    """Run debate with MiroFish routing and local fallback.

    Checks the `mirofish_enabled` flag in SystemSettings:
    - If enabled: Attempts to fetch signals from MiroFish API
    - If disabled or MiroFish fails: Falls back to local DebateEngine

    Args:
        db: Database session for settings lookup
        question: Market question
        market_price: Current YES price [0, 1]
        volume: 24h trading volume in USD
        category: Market category (e.g. "crypto", "politics")
        context: Additional context (news, data)
        max_rounds: Maximum debate rounds (1-2)
        data_sources: List of data source labels
        signal_votes: Optional pre-existing signal votes

    Returns:
        DebateResult with consensus probability, or None on total failure
    """
    start_time = time.time()

    # Check if MiroFish is enabled
    mirofish_enabled = _get_setting(db, "mirofish_enabled", default=False)

    if not mirofish_enabled:
        logger.info(
            "[debate_router] MiroFish disabled - using local DebateEngine"
        )
        return await run_debate(
            question=question,
            market_price=market_price,
            volume=volume,
            category=category,
            context=context,
            max_rounds=max_rounds,
            data_sources=data_sources,
            signal_votes=signal_votes,
        )

    # Try MiroFish first
    logger.info("[debate_router] MiroFish enabled - attempting API call")

    try:
        client = MiroFishClient()
        signals = await client.fetch_signals(market="polymarket")

        if signals:
            latency_ms = (time.time() - start_time) * 1000
            logger.info(
                "[debate_router] MiroFish success: %d signal(s) in %.2fms",
                len(signals),
                latency_ms,
            )
            return _convert_signals_to_debate_result(
                signals=signals,
                question=question,
                market_price=market_price,
                latency_ms=latency_ms,
            )
        else:
            logger.warning(
                "[debate_router] MiroFish returned empty signals - falling back to local"
            )

    except Exception as exc:
        logger.warning(
            "[debate_router] MiroFish failed (%s: %s) - falling back to local",
            type(exc).__name__,
            exc,
        )

    # Fallback to local DebateEngine
    logger.info("[debate_router] Using local DebateEngine fallback")
    return await run_debate(
        question=question,
        market_price=market_price,
        volume=volume,
        category=category,
        context=context,
        max_rounds=max_rounds,
        data_sources=data_sources,
        signal_votes=signal_votes,
    )
