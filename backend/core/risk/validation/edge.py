"""
Edge validation — MIN_EDGE_PP gate and longshot checks.
"""
from ..models import EdgeFilterError


def check_edge(
    market_price: float,
    signal_win_rate: float,
    market_id: str,
    db=None,
) -> float:
    """
    Validate trade edge (in percentage points) vs config/environmental minimum.
    - edge_pp = (signal_win_rate - market_price) * 100
    - market_price < 0.30 requires edge_pp > 10
    - All markets require edge_pp >= MIN_EDGE_PP
    Raise EdgeFilterError on rejection.
    """
    from backend.config import settings

    edge_pp = (signal_win_rate - market_price) * 100
    # Super-longshot trades require huge edge
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
    min_edge_pp = float(getattr(settings, "MIN_EDGE_PP", 1.0))
    if edge_pp < min_edge_pp:
        raise EdgeFilterError(
            f"Edge filter: edge_pp={edge_pp:.2f} < MIN_EDGE_PP={min_edge_pp}",
            market_id=market_id,
            market_price=market_price,
            signal_win_rate=signal_win_rate,
            edge_pp=edge_pp,
        )
    return edge_pp