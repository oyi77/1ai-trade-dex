"""Carved verbatim out of ``backend/core/backtester.py`` — statements moved, no logic changed."""

from __future__ import annotations

from ._backtester_backtestconfig import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
)

from .backtester import (
    Any,
    Session,
    Signal,
    datetime,
)

from . import backtester as _facade

class BacktestEngine:
    """Simulate strategy execution against historical market data."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    async def run(self, db: Session = None) -> BacktestResult:
        """
        Main entry point. Fetches historical signals from DB for the strategy
        and date range. Falls back to historical trades if no signals found.
        """
        _owned = db is None
        if _owned:
            db = _facade.SessionLocal()
        try:
            signals = self._fetch_signals(db)
            if signals:
                _facade.logger.info(
                    f"[backtester] Running signal-based backtest: {len(signals)} signals "
                    f"for strategy={self.config.strategy_name}"
                )
                return self._simulate_from_signals(signals, db)
            else:
                _facade.logger.info(
                    f"[backtester] No signals found for strategy={self.config.strategy_name}, "
                    f"falling back to trade replay"
                )
                return await self.run_from_trades(db)
        finally:
            if _owned:
                db.close()

    def _fetch_signals(self, db: Session) -> list[Signal]:
        """Fetch historical signals matching strategy and date range."""
        query = (
            db.query(_facade.Signal)
            .filter(
                _facade.Signal.timestamp >= self.config.start_date,
                _facade.Signal.timestamp <= self.config.end_date,
            )
            .order_by(_facade.Signal.timestamp.asc())
        )
        if self.config.strategy_name:
            query = query.filter(_facade.Signal.reasoning.contains(self.config.strategy_name))
        return query.all()

    def _simulate_from_signals(
        self, signals: list[Signal], db: Session
    ) -> BacktestResult:
        """Simulate trades from signal records."""
        bankroll = self.config.initial_bankroll
        equity_curve: list[dict] = []
        bt_trades: list[_facade.BacktestTrade] = []

        # Track daily loss per calendar date
        daily_pnl: dict[_facade.date, float] = {}
        total_exposure = 0.0
        peak_bankroll = self.config.initial_bankroll
        bucket_stats: dict[float, list[int]] = {}  # price bucket -> [wins, total]
        recent_returns: list[float] = []  # last N per-trade returns (pnl/bankroll)

        for sig in signals:
            if sig.edge is None or sig.edge <= 0:
                continue
            if sig.edge < self.config.min_edge_threshold:
                continue
            sig_mp = getattr(sig, "model_probability", None)
            if (
                self.config.min_model_probability > 0
                and sig_mp is not None
                and sig_mp < self.config.min_model_probability
            ):
                continue

            trade_date = sig.timestamp.date()

            # Daily loss limit check
            day_loss = daily_pnl.get(trade_date, 0.0)
            if day_loss <= -self.config.daily_loss_limit:
                _facade.logger.debug(
                    f"[backtester] Daily loss limit hit on {trade_date}, skipping signal"
                )
                continue

            # Position sizing
            entry_price = (
                sig.market_price
                if getattr(sig, "market_price", None) is not None
                else 0.5
            )
            if self.config.sizing_mode == "binary_kelly":
                win_prob = getattr(sig, "model_probability", None)
                if win_prob is None:
                    # edge ≡ model_prob − market_price ⇒ exact reconstruction
                    win_prob = entry_price + (sig.edge or 0.0)
                if self.config.calibration_shrinkage > 0:
                    bucket = round(
                        _facade.math.floor(entry_price / self.config.calibration_bucket)
                        * self.config.calibration_bucket,
                        4,
                    )
                    bkey = (
                        f"{bucket}:{sig.direction}"
                        if self.config.calibration_key == "price_dir"
                        else bucket
                    )
                    wins, total = bucket_stats.get(bkey, (0, 0))
                    k = self.config.calibration_shrinkage
                    win_prob = (win_prob * k + wins) / (k + total)
                f_star = _facade.kelly_fraction(
                    win_prob=win_prob,
                    price=entry_price,
                    cap=self.config.kelly_cap,
                )
                if self.config.vol_scaling and len(recent_returns) >= 3:
                    mean_r = sum(recent_returns) / len(recent_returns)
                    var = sum((r - mean_r) ** 2 for r in recent_returns) / len(recent_returns)
                    realized = _facade.math.sqrt(var)
                    if realized > 0:
                        f_star *= max(
                            self.config.vol_scale_floor,
                            min(1.0, self.config.vol_target / realized),
                        )
                kelly_size = bankroll * f_star
            else:
                kelly_size = bankroll * self.config.kelly_fraction * sig.edge
            size = min(
                kelly_size,
                self.config.max_trade_size,
                bankroll * self.config.max_position_fraction,
            )
            if self.config.drawdown_throttle and peak_bankroll > 0:
                dd = max(0.0, (peak_bankroll - bankroll) / peak_bankroll)
                size *= max(self.config.drawdown_throttle_floor, 1.0 - 5.0 * dd)
            if size <= 0:
                continue

            # Total exposure check
            if (total_exposure + size) / bankroll > self.config.max_total_exposure:
                continue

            settlement_value = sig.settlement_value

            # Determine PnL from settlement
            # size = dollars spent, entry_price = price per share
            # WIN: shares = size/entry_price, payout = shares * $1, pnl = payout - size
            # LOSS: pnl = -size (lose entire investment)
            pnl: float | None = None
            settled = False
            if settlement_value is not None:
                settled = True
                bt_direction = sig.direction
                if bt_direction in ("up", "yes"):
                    pnl = (
                        (size / entry_price) - size
                        if settlement_value == 1.0
                        else -size
                    )
                else:
                    pnl = (
                        (size / entry_price) - size
                        if settlement_value == 0.0
                        else -size
                    )
            elif sig.outcome_correct is not None:
                settled = True
                if sig.outcome_correct:
                    # Correct PnL: shares pay $1 each on win
                    # pnl = (size / entry_price) - size
                    pnl = (size / entry_price) - size if entry_price > 0 else 0.0
                else:
                    pnl = -size

            # Apply slippage cost (spread)
            if pnl is not None:
                if self.config.slippage_mode == "bps":
                    cost = self.config.slippage_bps / 10_000.0 * entry_price
                else:
                    cost = self.config.slippage
                pnl = round(pnl - cost, 4)

            bt_trade = _facade.BacktestTrade(
                timestamp=sig.timestamp,
                market_ticker=sig.market_ticker,
                direction=sig.direction or "up",
                entry_price=entry_price,
                size=size,
                edge=sig.edge,
                settlement_value=settlement_value,
                pnl=pnl,
                settled=settled,
            )
            bt_trades.append(bt_trade)

            if pnl is not None:
                bankroll += pnl
                peak_bankroll = max(peak_bankroll, bankroll)
                total_exposure = max(0.0, total_exposure - size)
                daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + pnl
                if self.config.vol_scaling:
                    recent_returns.append(pnl / bankroll if bankroll > 0 else 0.0)
                    if len(recent_returns) > self.config.vol_lookback:
                        recent_returns.pop(0)
                # Walk-forward calibration update (past-only by construction)
                if self.config.calibration_shrinkage > 0:
                    bucket = round(
                        _facade.math.floor(entry_price / self.config.calibration_bucket)
                        * self.config.calibration_bucket,
                        4,
                    )
                    bkey = (
                        f"{bucket}:{sig.direction}"
                        if self.config.calibration_key == "price_dir"
                        else bucket
                    )
                    st = bucket_stats.setdefault(bkey, [0, 0])
                    st[0] += 1 if pnl > 0 else 0
                    st[1] += 1
            else:
                total_exposure += size

            equity_curve.append(
                {
                    "timestamp": sig.timestamp.isoformat(),
                    "bankroll": round(bankroll, 4),
                }
            )

        metrics = self._calculate_metrics(
            bt_trades, equity_curve, self.config.initial_bankroll
        )
        return _facade.BacktestResult(
            config=self.config,
            trades=bt_trades,
            equity_curve=equity_curve,
            **metrics,
        )

    async def run_from_trades(self, db: Session = None) -> BacktestResult:
        """
        Backtest using actual historical Trade records from the DB.
        Replays settled trades chronologically with the config's risk parameters.
        """
        _owned = db is None
        if _owned:
            db = _facade.SessionLocal()
        try:
            trades = (
                db.query(_facade.Trade)
                .filter(
                    _facade.Trade.timestamp >= self.config.start_date,
                    _facade.Trade.timestamp <= self.config.end_date,
                    _facade.Trade.settled.is_(True),
                )
                .order_by(_facade.Trade.timestamp.asc())
                .all()
            )

            if self.config.strategy_name:
                trades = [t for t in trades if t.strategy == self.config.strategy_name]

            _facade.logger.info(f"[backtester] Replaying {len(trades)} settled trades")

            bankroll = self.config.initial_bankroll
            equity_curve: list[dict] = []
            bt_trades: list[_facade.BacktestTrade] = []

            daily_pnl: dict[_facade.date, float] = {}

            for trade in trades:
                trade_date = trade.timestamp.date()

                day_loss = daily_pnl.get(trade_date, 0.0)
                if day_loss <= -self.config.daily_loss_limit:
                    continue

                edge = trade.edge_at_entry or 0.02
                kelly_size = bankroll * self.config.kelly_fraction * edge
                size = min(
                    kelly_size,
                    self.config.max_trade_size,
                    bankroll * self.config.max_position_fraction,
                )
                if size <= 0:
                    continue

                entry_price = trade.entry_price or 0.5
                settlement_value = trade.settlement_value

                pnl: float | None = None
                if settlement_value is not None:
                    bt_dir = trade.direction
                    if bt_dir in ("up", "yes"):
                        pnl = (
                            (size / entry_price) - size
                            if settlement_value == 1.0
                            else -size
                        )
                    else:
                        pnl = (
                            (size / entry_price) - size
                            if settlement_value == 0.0
                            else -size
                        )
                elif trade.pnl is not None:
                    # Scale original pnl proportionally
                    orig_size = trade.size or size
                    scale = size / orig_size if orig_size > 0 else 1.0
                    pnl = trade.pnl * scale

                # Apply slippage cost
                if pnl is not None:
                    pnl = round(pnl - self.config.slippage, 4)

                bt_trade = _facade.BacktestTrade(
                    timestamp=trade.timestamp,
                    market_ticker=trade.market_ticker,
                    direction=trade.direction or "up",
                    entry_price=entry_price,
                    size=size,
                    edge=edge,
                    settlement_value=settlement_value,
                    pnl=pnl,
                    settled=True,
                )
                bt_trades.append(bt_trade)

                if pnl is not None:
                    bankroll += pnl
                    daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + pnl

                equity_curve.append(
                    {
                        "timestamp": trade.timestamp.isoformat(),
                        "bankroll": round(bankroll, 4),
                    }
                )

            metrics = self._calculate_metrics(
                bt_trades, equity_curve, self.config.initial_bankroll
            )
            return _facade.BacktestResult(
                config=self.config,
                trades=bt_trades,
                equity_curve=equity_curve,
                **metrics,
            )
        finally:
            if _owned:
                db.close()

    def _calculate_metrics(
        self,
        trades: list[BacktestTrade],
        equity_curve: list[dict],
        initial_bankroll: float,
    ) -> dict:
        """Compute performance metrics from completed trades."""
        settled = [t for t in trades if t.pnl is not None]
        wins = [t for t in settled if t.pnl > 0]
        losses = [t for t in settled if t.pnl <= 0]

        total_trades = len(settled)
        winning_trades = len(wins)
        total_pnl = sum(t.pnl for t in settled)
        final_bankroll = initial_bankroll + total_pnl
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        avg_edge = sum(t.edge for t in trades) / len(trades) if trades else 0.0
        avg_trade_size = sum(t.size for t in trades) / len(trades) if trades else 0.0
        return_pct = (
            (final_bankroll - initial_bankroll) / initial_bankroll * 100
            if initial_bankroll > 0
            else 0.0
        )

        # Max drawdown from equity curve peak-to-trough
        max_drawdown = 0.0
        if equity_curve:
            peak = equity_curve[0]["bankroll"]
            for point in equity_curve:
                b = point["bankroll"]
                if b > peak:
                    peak = b
                dd = (peak - b) / peak if peak > 0 else 0.0
                if dd > max_drawdown:
                    max_drawdown = dd

        # Compute per-trade returns (pnl / size = return per dollar risked)
        returns = [t.pnl / t.size for t in settled if t.size > 0]

        # Sharpe ratio: mean(returns) / std(returns) * sqrt(trades_per_year)
        # Use trade-count-based annualization instead of calendar-day assumption
        sharpe_ratio = 0.0
        if len(returns) > 1:
            mean_r = _facade.statistics.mean(returns)
            std_r = _facade.statistics.stdev(returns)
            if std_r > 0:
                # Estimate trades per year from sample
                trades_per_year = max(len(returns), 52)  # at least weekly
                sharpe_ratio = (mean_r / std_r) * (trades_per_year**0.5)

        # Sortino ratio: mean(returns) / downside_std * sqrt(trades_per_year)
        sortino_ratio = 0.0
        if len(returns) > 1:
            mean_r = _facade.statistics.mean(returns)
            downside = [r for r in returns if r < 0]
            if len(downside) > 1:
                downside_std = _facade.statistics.stdev(downside)
                if downside_std > 0:
                    trades_per_year = max(len(returns), 52)
                    sortino_ratio = (mean_r / downside_std) * (trades_per_year**0.5)

        # Profit Factor: gross wins / abs(gross losses)
        gross_wins = sum(t.pnl for t in wins)
        gross_losses = abs(sum(t.pnl for t in losses)) if losses else 0.0
        profit_factor = (
            gross_wins / gross_losses
            if gross_losses > 0
            else (float("inf") if gross_wins > 0 else 0.0)
        )

        return {
            "total_pnl": round(total_pnl, 4),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": round(win_rate, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "sortino_ratio": round(sortino_ratio, 4),
            "profit_factor": round(min(profit_factor, 999.0), 4),
            "avg_edge": round(avg_edge, 4),
            "avg_trade_size": round(avg_trade_size, 4),
            "final_bankroll": round(final_bankroll, 4),
            "return_pct": round(return_pct, 4),
        }

    async def run_from_historical_markets(
        self,
        strategy_fn: callable | None = None,
        db: Session = None,
    ) -> BacktestResult:
        """Backtest against historical resolved markets from Polymarket.

        Fetches MarketOutcome rows, pairs BTC markets with candle data,
        and replays strategy decisions. If strategy_fn is provided, calls
        it for each market to get (direction, model_probability, edge).
        Otherwise uses a simple momentum-based heuristic.
        """
        _owned = db is None
        if _owned:
            db = _facade.SessionLocal()
        try:
            from backend.models.historical_data import MarketOutcome

            query = (
                db.query(MarketOutcome)
                .filter(
                    MarketOutcome.resolution_time >= self.config.start_date,
                    MarketOutcome.resolution_time <= self.config.end_date,
                )
                .order_by(MarketOutcome.resolution_time.asc())
            )

            outcomes = query.all()
            if not outcomes:
                _facade.logger.info("[backtester] No historical market outcomes found")
                return self._empty_result()

            _facade.logger.info(
                "[backtester] Running historical market backtest: %d resolved markets",
                len(outcomes),
            )

            bankroll = self.config.initial_bankroll
            equity_curve: list[dict] = []
            bt_trades: list[_facade.BacktestTrade] = []
            daily_pnl: dict[_facade.date, float] = {}
            total_exposure = 0.0

            for outcome in outcomes:
                resolution_dt = outcome.resolution_time
                if resolution_dt is None:
                    continue

                trade_date = resolution_dt.date()

                day_loss = daily_pnl.get(trade_date, 0.0)
                if day_loss <= -self.config.daily_loss_limit:
                    continue

                final_price = outcome.final_price or 0.5

                if strategy_fn:
                    decision = await strategy_fn(outcome, db)
                    if decision is None:
                        continue
                    direction, model_prob, edge = decision
                else:
                    direction, model_prob, edge = self._default_decision(
                        outcome, resolution_dt, db
                    )

                if edge <= 0:
                    continue

                entry_price = final_price if direction == "up" else (1.0 - final_price)
                entry_price = max(0.01, min(0.99, entry_price))

                kelly_size = bankroll * self.config.kelly_fraction * edge
                size = min(
                    kelly_size,
                    self.config.max_trade_size,
                    bankroll * self.config.max_position_fraction,
                )
                if size <= 0:
                    continue

                if (total_exposure + size) / bankroll > self.config.max_total_exposure:
                    continue

                won = (direction == "up" and outcome.outcome in ("Yes", "up")) or (
                    direction == "down" and outcome.outcome in ("No", "down")
                )
                pnl = ((size / entry_price) - size) if won else -size
                pnl = round(pnl - self.config.slippage, 4)

                bt_trade = _facade.BacktestTrade(
                    timestamp=resolution_dt,
                    market_ticker=outcome.market_ticker or "",
                    direction=direction,
                    entry_price=entry_price,
                    size=size,
                    edge=edge,
                    settlement_value=1.0 if won else 0.0,
                    pnl=pnl,
                    settled=True,
                )
                bt_trades.append(bt_trade)

                if pnl is not None:
                    bankroll += pnl
                    total_exposure = max(0.0, total_exposure - size)
                    daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + pnl

                equity_curve.append(
                    {
                        "timestamp": resolution_dt.isoformat(),
                        "bankroll": round(bankroll, 4),
                    }
                )

            metrics = self._calculate_metrics(
                bt_trades, equity_curve, self.config.initial_bankroll
            )
            return _facade.BacktestResult(
                config=self.config,
                trades=bt_trades,
                equity_curve=equity_curve,
                **metrics,
            )
        finally:
            if _owned:
                db.close()

    def _default_decision(
        self,
        outcome: Any,
        resolution_dt: datetime,
        db: Session,
    ) -> tuple[str, float, float]:
        """Default backtest decision: momentum heuristic from BTC candles."""
        from backend.models.historical_data import HistoricalCandle

        raw_data = outcome.raw_data or {}
        category = outcome.category or ""
        is_btc = (
            "btc" in category.lower()
            or "bitcoin" in (raw_data.get("question") or "").lower()
            or "btc" in (raw_data.get("slug") or "").lower()
        )

        if not is_btc:
            return "up", 0.5, 0.0

        _resolution_ts = resolution_dt.timestamp() if resolution_dt else 0
        candle = (
            db.query(HistoricalCandle)
            .filter(
                HistoricalCandle.symbol == "BTCUSDT",
                HistoricalCandle.timestamp <= resolution_dt,
            )
            .order_by(HistoricalCandle.timestamp.desc())
            .first()
        )

        if not candle:
            return "up", 0.5, 0.0

        momentum = (
            (candle.close - candle.open) / candle.open if candle.open > 0 else 0.0
        )
        direction = "up" if momentum > 0 else "down"
        model_prob = 0.50 + min(abs(momentum) * 5.0, 0.10)

        entry = (
            outcome.final_price
            if direction == "up"
            else (1.0 - (outcome.final_price or 0.5))
        )
        entry = max(0.01, min(0.99, entry or 0.5))
        edge = abs(model_prob - entry)

        return direction, model_prob, edge

    def run_with_params(
        self,
        strategy_name: str,
        param_overrides: dict[str, Any],
        db: Session | None = None,
    ) -> BacktestResult:
        """RL-style parameterized backtest: replay settled trades with arbitrary param overrides.

        Reads historical Trade rows for the strategy, replays them applying param_overrides
        to sizing (kelly_fraction, max_trade_size, min_edge) and cost (slippage) calculations.
        Returns a full BacktestResult for comparison against baseline.

        Args:
            strategy_name: Strategy to replay trades for.
            param_overrides: Keys override BacktestConfig fields (kelly_fraction, slippage,
                max_trade_size, max_position_fraction, daily_loss_limit) AND strategy-specific
                params (min_edge, cooldown_minutes, etc.).
            db: Optional session; creates own if None.
        """
        _owned = db is None
        if _owned:
            db = _facade.SessionLocal()
        try:
            cfg = self.config
            kelly = float(param_overrides.get("kelly_fraction", cfg.kelly_fraction))
            max_size = float(param_overrides.get("max_trade_size", cfg.max_trade_size))
            slippage = float(param_overrides.get("slippage", cfg.slippage))
            max_pos_frac = float(
                param_overrides.get("max_position_fraction", cfg.max_position_fraction)
            )
            min_edge = float(param_overrides.get("min_edge", 0.0))
            daily_limit = float(
                param_overrides.get("daily_loss_limit", cfg.daily_loss_limit)
            )

            trades = (
                db.query(_facade.Trade)
                .filter(
                    _facade.Trade.strategy == strategy_name,
                    _facade.Trade.settled.is_(True),
                    _facade.Trade.timestamp >= cfg.start_date,
                    _facade.Trade.timestamp <= cfg.end_date,
                )
                .order_by(_facade.Trade.timestamp.asc())
                .all()
            )

            bankroll = cfg.initial_bankroll
            equity_curve: list[dict] = []
            bt_trades: list[_facade.BacktestTrade] = []
            daily_pnl: dict[_facade.date, float] = {}
            total_exposure = 0.0

            for trade in trades:
                trade_date = trade.timestamp.date()
                day_loss = daily_pnl.get(trade_date, 0.0)
                if day_loss <= -daily_limit:
                    continue

                edge = (
                    trade.edge_at_entry
                    if hasattr(trade, "edge_at_entry") and trade.edge_at_entry
                    else 0.1
                )
                if edge < min_edge:
                    continue

                kelly_size = bankroll * kelly * edge
                size = min(kelly_size, max_size, bankroll * max_pos_frac)
                if size <= 0:
                    continue

                if (total_exposure + size) / max(
                    bankroll, 1.0
                ) > cfg.max_total_exposure:
                    continue

                entry_price = trade.entry_price or 0.5
                settlement_value = trade.settlement_value

                pnl: float | None = None
                if settlement_value is not None:
                    bt_dir = trade.direction
                    if bt_dir in ("up", "yes"):
                        pnl = (
                            ((size / entry_price) - size)
                            if settlement_value == 1.0
                            else -size
                        )
                    else:
                        pnl = (
                            ((size / entry_price) - size)
                            if settlement_value == 0.0
                            else -size
                        )
                elif trade.pnl is not None:
                    orig_size = trade.size or size
                    scale = size / orig_size if orig_size > 0 else 1.0
                    pnl = trade.pnl * scale

                if pnl is not None:
                    pnl = round(pnl - slippage, 4)

                bt_trades.append(
                    _facade.BacktestTrade(
                        timestamp=trade.timestamp,
                        market_ticker=trade.market_ticker,
                        direction=trade.direction or "up",
                        entry_price=entry_price,
                        size=size,
                        edge=edge,
                        settlement_value=settlement_value,
                        pnl=pnl,
                        settled=True,
                    )
                )

                if pnl is not None:
                    bankroll += pnl
                    total_exposure = max(0.0, total_exposure - size)
                    daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + pnl
                else:
                    total_exposure += size

                equity_curve.append(
                    {
                        "timestamp": trade.timestamp.isoformat(),
                        "bankroll": round(bankroll, 4),
                    }
                )

            metrics = self._calculate_metrics(
                bt_trades, equity_curve, cfg.initial_bankroll
            )
            return _facade.BacktestResult(
                config=cfg, trades=bt_trades, equity_curve=equity_curve, **metrics
            )
        finally:
            if _owned:
                db.close()

    def _empty_result(self) -> BacktestResult:
        return _facade.BacktestResult(
            config=self.config,
            trades=[],
            equity_curve=[],
            total_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            win_rate=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            profit_factor=0.0,
            avg_edge=0.0,
            avg_trade_size=0.0,
            final_bankroll=self.config.initial_bankroll,
            return_pct=0.0,
        )
