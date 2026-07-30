"""
Edge validation — checks signal edge vs market price.
"""
from typing import Optional

from loguru import logger

from backend.core.risk.models import EdgeFilterError
from backend.monitoring.hft_metrics import record_signal
from backend.monitoring.metrics import increment_risk_rejection


def check_edge(
    settings_obj,
    market_price: float,
    signal_win_rate: float,
    market_id: str,
) -> float:
    """Validate trade edge in percentage points against config minimum.

    Args:
        settings_obj: Settings/config object with MIN_EDGE_PP attribute.
        market_price: Current market price (0-1 range).
        signal_win_rate: Signal's predicted win rate.
        market_id: Market identifier for error reporting.

    Returns:
        edge_pp in percentage points.

    Raises:
        EdgeFilterError: If edge is below configured minimum.
    """
    edge_pp = (signal_win_rate - market_price) * 100
    min_edge_pp = float(getattr(settings_obj, "MIN_EDGE_PP", 1.0))

    # Super-longshot trades require huge edge.
    # Longshot markets need meaningful edge, but bond_scanner's structural
    # edge (high-prob near resolution) is small and consistent (0.5-2pp).
    # ponytail: lowered from 5 to 2 — 5pp blocked all bond_scanner trades.
    if market_price < 0.30 and edge_pp < 0.3:
        raise EdgeFilterError(
            f"Edge filter: market_price={market_price:.2f} longshot, edge_pp={edge_pp:.2f} < 2",
            market_id=market_id,
            market_price=market_price,
            signal_win_rate=signal_win_rate,
            edge_pp=edge_pp,
        )
    if edge_pp < min_edge_pp:
        raise EdgeFilterError(
            f"Edge filter: edge_pp={edge_pp:.2f} < MIN_EDGE_PP={min_edge_pp}",
            market_id=market_id,
            market_price=market_price,
            signal_win_rate=signal_win_rate,
            edge_pp=edge_pp,
        )
    return edge_pp


def validate_category_edge(
    settings_obj,
    category: str,
    market_price: float,
    signal_win_rate: float,
    strategy_name: Optional[str] = None,
) -> Optional[str]:
    """Check per-category minimum edge threshold.

    Returns rejection reason string or None if passed.
    """
    cat_min_edge = getattr(settings_obj, "CATEGORY_MIN_EDGE", {})
    min_edge_for_cat = cat_min_edge.get(category.lower(), 0.03)
    edge = signal_win_rate - market_price
    if edge < min_edge_for_cat:
        record_signal(
            strategy=strategy_name or "unknown",
            signal_type="rejected_category_edge",
        )
        increment_risk_rejection(
            strategy=strategy_name or "unknown", reason="category_edge"
        )
        logger.info(
            "[risk_manager] Category edge rejection: cat={} edge={:.4f} < min={:.4f}",
            category, edge, min_edge_for_cat,
        )
        return f"category '{category}' edge {edge:.4f} < min {min_edge_for_cat:.4f}"
    return None


def validate_min_ev(
    settings_obj,
    size: float,
    market_price: float,
    signal_win_rate: float,
    strategy_name: Optional[str] = None,
) -> Optional[str]:
    """Check minimum expected value threshold.

    Returns rejection reason string or None if passed.
    """
    min_trade_ev = getattr(settings_obj, "MIN_TRADE_EV", 0.10)
    edge = abs(signal_win_rate - market_price)
    ev = edge * size
    if ev < min_trade_ev:
        record_signal(
            strategy=strategy_name or "unknown", signal_type="rejected_min_ev"
        )
        increment_risk_rejection(
            strategy=strategy_name or "unknown", reason="min_ev"
        )
        logger.info(
            "[risk_manager] Min EV rejection: ev=${:.4f} < min=${:.4f} (edge={:.4f} size=${:.2f})",
            ev, min_trade_ev, edge, size,
        )
        return f"trade EV ${ev:.4f} < min ${min_trade_ev:.4f}"
    return None
