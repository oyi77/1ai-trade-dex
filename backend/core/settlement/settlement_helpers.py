"""
Settlement helper functions — re-export layer for backward compatibility.

All functions have been extracted to domain-specific modules:
- resolution.py  — Polymarket/Kalshi/Binance API resolution
- calculate_pnl.py — P&L calculation math
- weather.py — Weather settlement and calibration
- process.py — Settlement processing pipeline
- reconcile.py — Position reconciliation + paper trade resolution
"""

from backend.core.settlement.calculate_pnl import (
    calculate_pnl,
    calculate_exit_pnl,
    total_loss_settlement_value,
)
from backend.core.settlement.process import (
    check_market_settlement,
    process_settled_trade,
)
from backend.core.settlement.reconcile import (
    reconcile_positions,
    resolve_paper_trades,
)
from backend.core.settlement.resolution import (
    _check_clob_resolution,
    _check_event_concluded,
    _fetch_kalshi_resolution,
    _has_invalid_prices,
    _looks_like_token_id,
    _parse_market_resolution,
    _resolve_btc_updown_via_binance,
    _resolve_pm_by_token_id,
    _search_market_in_events,
    fetch_polymarket_resolution,
    fetch_resolution_for_trade,
)
from backend.core.settlement.weather import (
    _get_actual_temp_from_openmeteo,
    _record_weather_observation,
    _resolve_markets,
    _try_calibrate_weather,
    check_weather_settlement,
)

__all__ = [
    # resolution
    "fetch_polymarket_resolution",
    "fetch_resolution_for_trade",
    "_looks_like_token_id",
    "_resolve_pm_by_token_id",
    "_has_invalid_prices",
    "_check_clob_resolution",
    "_search_market_in_events",
    "_parse_market_resolution",
    "_check_event_concluded",
    "_resolve_btc_updown_via_binance",
    "_fetch_kalshi_resolution",
    # pnl
    "calculate_pnl",
    "calculate_exit_pnl",
    "total_loss_settlement_value",
    # weather
    "check_weather_settlement",
    "_get_actual_temp_from_openmeteo",
    "_resolve_markets",
    "_try_calibrate_weather",
    "_record_weather_observation",
    # process
    "check_market_settlement",
    "process_settled_trade",
    # reconcile
    "reconcile_positions",
    "resolve_paper_trades",
]
