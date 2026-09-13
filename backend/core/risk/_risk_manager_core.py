"""RiskManager core mixin — init, edge check, bankroll, safety rules."""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, or_

from loguru import logger

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade, BotState, for_update
from backend.monitoring.hft_metrics import record_signal, db_query_duration
from backend.monitoring.metrics import increment_risk_rejection
from backend.core.risk.correlation_monitor import CorrelationMonitor

from backend.core.risk._risk_manager_types import (
    RiskDecision,
    EdgeFilterError,
    DrawdownStatus,
    IMMUTABLE_SAFETY_RULES,
    _not_backfill_settlement_source,
)



class RiskManagerCoreMixin:
    """Mixin — method implementations live on RiskManager."""

    def __init__(self, settings_obj=None):
        self.s = settings_obj or settings
        self._mode_failure_counts: dict[str, int] = {}
        self._safety_rules = self._load_safety_rules()
        self.MIN_EDGE_PP = float(getattr(self.s, "MIN_EDGE_PP", 1.0))
        self._correlation_monitor = CorrelationMonitor(settings_obj)
        self._calibration_cache = None
        self._calibration_cache_time = None
        self._longshot_bias_cache = None
        self._longshot_bias_cache_time = None

    def check_edge(
        self, market_price: float, signal_win_rate: float, market_id: str, db=None
    ):
        """
        Validate trade edge (in percentage points) vs config/environmental minimum.
        - edge_pp = (signal_win_rate - market_price) * 100
        - market_price < 0.30 requires edge_pp > 10
        - All markets require edge_pp >= MIN_EDGE_PP
        Raise EdgeFilterError on rejection.
        """
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
        if edge_pp < self.MIN_EDGE_PP:
            raise EdgeFilterError(
                f"Edge filter: edge_pp={edge_pp:.2f} < MIN_EDGE_PP={self.MIN_EDGE_PP}",
                market_id=market_id,
                market_price=market_price,
                signal_win_rate=signal_win_rate,
                edge_pp=edge_pp,
            )
        return edge_pp

    def _get_bankroll(self, db, mode: str) -> float:
        _qstart = time.monotonic()
        state = db.query(BotState).filter_by(mode=mode).first()
        try:
            db_query_duration.labels(query_type="get_bankroll").observe(
                time.monotonic() - _qstart
            )
        except Exception:
            logger.exception(
                "[risk_manager.get_bankroll] failed to observe db_query_duration metric"
            )
        if state and state.bankroll is not None:
            return float(state.bankroll)
        return self.s.INITIAL_BANKROLL

    def _load_safety_rules(self) -> dict:
        """Load immutable safety rules with environment variable overrides."""
        import os

        rules = {}
        for rule_name, rule_config in IMMUTABLE_SAFETY_RULES.items():
            value = rule_config["default"]
            env_var = rule_config.get("override_env_var")
            if env_var:
                env_value = os.environ.get(env_var)
                if env_value is not None:
                    try:
                        if isinstance(value, float):
                            value = float(env_value)
                        elif isinstance(value, int):
                            value = int(env_value)
                        elif isinstance(value, bool):
                            value = env_value.lower() in ("true", "1", "yes")
                    except ValueError:
                        logger.warning(
                            f"Invalid value for {env_var}={env_value}, using default {value}"
                        )

            rules[rule_name] = value

        return rules

    def _breaker_enabled_for_mode(self, breaker: str, mode: str) -> bool:
        """Check whether a circuit breaker is enabled for the given trading mode.

        breaker: "drawdown" or "daily_loss"
        mode: "paper", "testnet", or "live"

        Paper mode defaults to breaker-disabled so it can run infinitely for
        backtest, frontest, and improvement loops. Testnet and live default
        to breaker-enabled for capital safety.
        """
        if breaker == "drawdown":
            config = self.s.DRAWDOWN_BREAKER_ENABLED_PER_MODE
        elif breaker == "daily_loss":
            config = self.s.DAILY_LOSS_LIMIT_ENABLED_PER_MODE
        else:
            return True
        return config.get(mode, True)

