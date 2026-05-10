"""Signal generator for BTC 5-minute Up/Down markets."""

import logging
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass, field
import asyncio

from backend.config import settings
from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets
from backend.data.crypto import compute_btc_microstructure
from backend.data.market_universe import MarketUniverseScanner
from backend.models.database import Signal

logger = logging.getLogger("trading_bot")


@dataclass
class TradingSignal:
    """A trading signal for a BTC 5-min market."""

    market: BtcMarket

    # Core signal data
    model_probability: float = 0.5  # Our estimated probability of UP
    market_probability: float = 0.5  # Market's implied UP probability
    edge: float = 0.0
    direction: str = "up"  # "up" or "down"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    execution_mode: str = "paper"  # "paper", "testnet", or "live"
    track_name: str = ""  # Strategy name for attribution

    # BTC price context
    btc_price: float = 0.0
    btc_change_1h: float = 0.0
    btc_change_24h: float = 0.0

    @property
    def passes_threshold(self) -> bool:
        """Check if signal passes minimum edge threshold."""
        return abs(self.edge) >= settings.MIN_EDGE_THRESHOLD


def calculate_edge(model_prob: float, market_price: float) -> tuple[float, str]:
    """Calculate edge and direction ("up"/"down") for a BTC 5-min market."""
    up_edge = model_prob - market_price
    down_edge = (1 - model_prob) - (1 - market_price)

    if up_edge >= down_edge:
        return up_edge, "up"
    else:
        return down_edge, "down"


def calculate_kelly_size(
    edge: float,
    probability: float,
    market_price: float,
    direction: str,
    bankroll: float,
    n_eff: Optional[int] = None,
    prior_confidence: float = 30.0,
) -> float:
    """Calculate position size using Bayesian Kelly criterion.

    Bayesian Kelly formula:
        f* = (p̄ - (1-p̄)/b) × n_eff / (n_eff + κ)

    Where:
        p̄   = estimated win probability
        b    = odds = (1 - price) / price
        n_eff = effective sample size (number of recent trades/observations)
        κ    = prior confidence (default 30) — higher values shrink sizing more

    When n_eff is None, the classic Kelly is used (no Bayesian shrinkage).
    Result is scaled by KELLY_FRACTION and clamped to f_max = 0.15 (15%).
    """
    if direction == "up":
        win_prob = probability
        price = market_price
    else:
        win_prob = 1 - probability
        price = 1 - market_price

    if price <= 0 or price >= 1:
        return 0

    odds = (1 - price) / price

    lose_prob = 1 - win_prob
    kelly = (win_prob * odds - lose_prob) / odds

    # Apply Bayesian shrinkage when sample size is provided
    if n_eff is not None and n_eff >= 0:
        kelly *= n_eff / (n_eff + prior_confidence)

    kelly *= settings.KELLY_FRACTION

    max_fraction = 0.15
    kelly = min(kelly, max_fraction)
    kelly = max(kelly, 0)

    size = kelly * bankroll
    size = min(size, settings.MAX_TRADE_SIZE)

    return size


async def generate_btc_signal(market: BtcMarket, mode: str = "paper") -> Optional[TradingSignal]:
    """Generate a trading signal for a BTC 5-min Up/Down market."""
    try:
        micro = await compute_btc_microstructure()
    except Exception as e:
        logger.warning(f"Failed to compute microstructure: {e}")
        return None

    if not micro:
        return None

    market_up_prob = market.up_price

    if market_up_prob < 0.02 or market_up_prob > 0.98:
        return None

    entry_price = market_up_prob

    # 1) RSI: mean reversion — oversold (< 30) = UP, overbought (> 70) = DOWN
    if micro.rsi < 30:
        rsi_signal = 0.5 + (30 - micro.rsi) / 30  # 0.5 to 1.0
    elif micro.rsi > 70:
        rsi_signal = -0.5 - (micro.rsi - 70) / 30  # -0.5 to -1.0
    elif micro.rsi < 45:
        rsi_signal = (45 - micro.rsi) / 30  # slight UP lean
    elif micro.rsi > 55:
        rsi_signal = -(micro.rsi - 55) / 30  # slight DOWN lean
    else:
        rsi_signal = 0.0
    rsi_signal = max(-1.0, min(1.0, rsi_signal))

    # 2) Momentum: weighted blend of 1m, 5m, 15m changes
    mom_blend = (
        micro.momentum_1m * 0.5 + micro.momentum_5m * 0.35 + micro.momentum_15m * 0.15
    )
    momentum_signal = max(-1.0, min(1.0, mom_blend / 0.10))

    # 3) VWAP deviation
    vwap_signal = max(-1.0, min(1.0, micro.vwap_deviation / 0.05))

    # 4) SMA crossover
    sma_signal = max(-1.0, min(1.0, micro.sma_crossover / 0.03))

    # 5) Market skew: contrarian fade
    market_skew = market_up_prob - 0.50
    skew_signal = max(-1.0, min(1.0, -market_skew * 4))

    indicator_signs = [
        rsi_signal,
        momentum_signal,
        vwap_signal,
        sma_signal,
    ]
    # Use a higher threshold (0.15) to avoid counting noise as a "vote"
    up_votes = sum(1 for s in indicator_signs if s > 0.15)
    down_votes = sum(1 for s in indicator_signs if s < -0.15)

    # Require 2 of 4 indicators to agree (relaxed from 3/4 for low-volatility environment)
    has_convergence = up_votes >= 2 or down_votes >= 2

    # Volatility gate: skip signals during low-volatility (random walk) periods
    # Lowered from 0.02% to 0.01% to allow trading in current low-volatility environment
    has_sufficient_volatility = micro.volatility >= 0.01

    w = settings
    composite = (
        rsi_signal * w.WEIGHT_RSI
        + momentum_signal * w.WEIGHT_MOMENTUM
        + vwap_signal * w.WEIGHT_VWAP
        + sma_signal * w.WEIGHT_SMA
        + skew_signal * w.WEIGHT_MARKET_SKEW
    )

    # Reduced multiplier: 0.10 instead of 0.15 — model should be LESS confident
    # given its track record of claiming edge that doesn't exist
    model_up_prob = 0.50 + composite * 0.10
    model_up_prob = max(0.40, min(0.60, model_up_prob))

    edge, direction = calculate_edge(model_up_prob, market_up_prob)

    if direction == "up":
        entry_price = market_up_prob
    else:
        entry_price = market.down_price

    now = datetime.now(timezone.utc)
    window_end = market.window_end
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    time_remaining = (window_end - now).total_seconds()
    time_ok = (
        settings.MIN_TIME_REMAINING <= time_remaining <= settings.MAX_TIME_REMAINING
    )

    passes_filters = (
        has_convergence
        and has_sufficient_volatility
        and entry_price <= settings.MAX_ENTRY_PRICE
        and time_ok
    )

    if not passes_filters:
        edge = 0.0

    convergence_strength = max(up_votes, down_votes) / 4.0
    base_confidence = 0.3 + convergence_strength * 0.3
    edge_component = min(0.2, abs(edge) / 0.2)
    composite_component = min(0.1, abs(composite) * 0.5)

    if micro.volatility > 0:
        vol_adjustment = max(0.8, min(1.0, micro.volatility / 0.01))
    else:
        vol_adjustment = 0.8

    confidence = min(
        0.95, (base_confidence + edge_component + composite_component) * vol_adjustment
    )

    bankroll = settings.INITIAL_BANKROLL
    try:
        from backend.models.database import BotState, for_update

        from backend.db.utils import get_db_session
        with get_db_session() as _db:
            _state = for_update(_db, _db.query(BotState).filter_by(mode=mode)).first()
            if _state:
                bankroll = float(
                    _state.bankroll if _state.bankroll is not None else settings.INITIAL_BANKROLL
                )
    except Exception as _e:
        logger.debug(f"Bankroll read failed for mode {mode}, using INITIAL_BANKROLL: {_e}")
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_up_prob,
        market_price=market_up_prob,
        direction=direction,
        bankroll=bankroll,
    )

    filter_status = "ACTIONABLE" if passes_filters else "FILTERED"
    filter_reasons = []
    if not has_convergence:
        filter_reasons.append(f"convergence {max(up_votes, down_votes)}/4 < 3")
    if not has_sufficient_volatility:
        filter_reasons.append(f"vol {micro.volatility:.4f}% < 0.02%")
    if not time_ok:
        filter_reasons.append(
            f"time {time_remaining:.0f}s not in [{settings.MIN_TIME_REMAINING},{settings.MAX_TIME_REMAINING}]"
        )
    if entry_price > settings.MAX_ENTRY_PRICE:
        filter_reasons.append(
            f"entry {entry_price:.0%} > {settings.MAX_ENTRY_PRICE:.0%}"
        )
    filter_note = f" [{', '.join(filter_reasons)}]" if filter_reasons else ""

    reasoning = (
        f"[{filter_status}]{filter_note} "
        f"BTC ${micro.price:,.0f} | RSI:{micro.rsi:.0f} Mom1m:{micro.momentum_1m:+.3f}% "
        f"Mom5m:{micro.momentum_5m:+.3f}% VWAP:{micro.vwap_deviation:+.3f}% "
        f"SMA:{micro.sma_crossover:+.4f}% Vol:{micro.volatility:.4f}% | "
        f"Composite:{composite:+.3f} -> Model UP:{model_up_prob:.0%} vs Mkt:{market_up_prob:.0%} | "
        f"Edge:{edge:+.1%} -> {direction.upper()} @ {entry_price:.0%} | "
        f"Convergence:{max(up_votes, down_votes)}/4 | "
        f"Window ends: {market.window_end.strftime('%H:%M UTC')}"
    )

    return TradingSignal(
        market=market,
        model_probability=model_up_prob,
        market_probability=market_up_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=[f"binance_microstructure_{micro.source}"],
        reasoning=reasoning,
        execution_mode=mode,
        track_name="btc_oracle",
        btc_price=micro.price,
        btc_change_1h=micro.momentum_5m * 12,
        btc_change_24h=micro.momentum_15m * 96,
    )


async def scan_for_signals(mode: str = "paper") -> List[TradingSignal]:
    signals = []

    logger.info("=" * 50)
    logger.info("BTC 5-MIN SCAN: Fetching markets from Polymarket...")

    try:
        markets = await fetch_active_btc_markets()
    except Exception as e:
        logger.error(f"Failed to fetch BTC markets: {e}")
        markets = []

    logger.info(f"Found {len(markets)} active BTC 5-min markets")

    for market in markets:
        try:
            signal = await generate_btc_signal(market, mode=mode)
            if signal:
                signals.append(signal)
        except Exception as e:
            logger.debug(f"Signal generation failed for {market.slug}: {e}")

        # Small delay to avoid CoinGecko rate limits
        # (only needed if we're making multiple calls - reuse first result)
        await asyncio.sleep(0.1)

    # Sort by absolute edge (best opportunities first)
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info("=" * 50)
    logger.info(f"SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable")

    for signal in actionable[:5]:
        logger.info(f"  {signal.market.slug}")
        logger.info(
            f"    Edge: {signal.edge:+.1%} -> {signal.direction.upper()} @ ${signal.suggested_size:.2f}"
        )

    # Persist signals with non-zero edge to DB for calibration tracking, but do
    # not let SQLite lock contention stall HTTP responses that only need the
    # freshly generated signal list.
    try:
        asyncio.create_task(_persist_signals_async(signals, mode=mode))
    except RuntimeError as exc:
        logger.warning(f"Failed to schedule signal persistence: {exc}")

    return signals


async def _persist_signals_async(signals: list, mode: str = "paper"):
    """Persist scan results off the request path."""

    await asyncio.to_thread(_persist_signals, signals, mode)


def _persist_signals(signals: list, mode: str = "paper"):
    to_save = [s for s in signals if abs(s.edge) > 0]
    if not to_save:
        return

    execution_mode = mode

    from backend.db.utils import get_db_session
    try:
        with get_db_session() as db:
            for signal in to_save:
                existing = (
                    db.query(Signal)
                    .filter(
                        Signal.market_ticker == signal.market.market_id,
                        Signal.timestamp
                        >= signal.timestamp.replace(second=0, microsecond=0),
                    )
                    .first()
                )
                if existing:
                    continue

                db_signal = Signal(
                    market_ticker=signal.market.market_id,
                    platform="polymarket",
                    timestamp=signal.timestamp,
                    direction=signal.direction,
                    model_probability=signal.model_probability,
                    market_price=signal.market_probability,
                    edge=signal.edge,
                    confidence=signal.confidence,
                    kelly_fraction=signal.kelly_fraction,
                    suggested_size=signal.suggested_size,
                    sources=signal.sources,
                    reasoning=signal.reasoning,
                    track_name=signal.track_name or "btc_oracle",
                    execution_mode=execution_mode,
                    executed=False,
                )
                db.add(db_signal)
                try:
                    from backend.core.event_bus import _broadcast_event

                    # Find the original signal to get full context
                    original_signal = next(
                        (
                            s
                            for s in signals
                            if s.market.market_id == db_signal.market_ticker
                        ),
                        None,
                    )
                    market_title = (
                        f"BTC {original_signal.market.window_start.strftime('%H:%M')} - {original_signal.market.window_end.strftime('%H:%M')} UTC"
                        if original_signal
                        else db_signal.market_ticker
                    )
                    _broadcast_event(
                        "signal_found",
                        {
                            "market_ticker": db_signal.market_ticker,
                            "market_title": market_title,
                            "direction": db_signal.direction,
                            "model_probability": db_signal.model_probability,
                            "market_probability": db_signal.market_price,
                            "edge": db_signal.edge,
                            "confidence": db_signal.confidence,
                            "suggested_size": db_signal.suggested_size,
                            "reasoning": db_signal.reasoning,
                            "timestamp": db_signal.timestamp.isoformat(),
                            "category": "trading",
                            "btc_price": original_signal.btc_price
                            if original_signal
                            else None,
                            "window_end": original_signal.market.window_end.isoformat()
                            if original_signal and original_signal.market.window_end
                            else None,
                            "actionable": abs(db_signal.edge) >= 0.02,
                            "event_slug": original_signal.market.slug
                            if original_signal
                            else None,
                        },
                    )
                except Exception as _e:
                    logger.debug(f"Event broadcast failed for signal: {_e}")

            db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist signals: {e}")
        db.rollback()


async def get_actionable_signals(mode: str = "paper") -> List[TradingSignal]:
    """Get only signals that pass the edge threshold."""
    all_signals = await scan_for_signals(mode=mode)
    return [s for s in all_signals if s.passes_threshold]


_universe_scanner: Optional[MarketUniverseScanner] = None


def get_universe_scanner() -> MarketUniverseScanner:
    """Lazy-initialized singleton for MarketUniverseScanner."""
    global _universe_scanner
    if _universe_scanner is None:
        _universe_scanner = MarketUniverseScanner()
    return _universe_scanner


async def scan_universe_markets(limit: int = 5000) -> list:
    """Scan the full market universe (5000+ markets) via MarketUniverseScanner."""
    scanner = get_universe_scanner()
    return await scanner.get_active_markets(limit=limit)


if __name__ == "__main__":

    async def test():
        print("Scanning BTC 5-min markets for signals...")
        signals = await scan_for_signals()
        print(f"\nFound {len(signals)} total signals")

        actionable = [s for s in signals if s.passes_threshold]
        print(
            f"Actionable signals (>{settings.MIN_EDGE_THRESHOLD:.0%} edge): {len(actionable)}"
        )

        for signal in actionable[:5]:
            print(f"\n{signal.market.slug}")
            print(f"  BTC: ${signal.btc_price:,.0f} ({signal.btc_change_24h:+.2f}%)")
            print(
                f"  Model UP: {signal.model_probability:.1%} vs Market UP: {signal.market_probability:.1%}"
            )
            print(f"  Edge: {signal.edge:+.1%} -> {signal.direction.upper()}")
            print(f"  Size: ${signal.suggested_size:.2f}")

    asyncio.run(test())
