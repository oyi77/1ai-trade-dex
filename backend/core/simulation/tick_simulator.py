"""
High-fidelity historical tick-replay simulator for HFT and Market Making backtesting.

Simulates Exchange matching engines, latency, and fills to validate pricing,
momentum, and quoting math over historical or mocked WebSocket streams.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Type
from loguru import logger

from backend.core.event_bus import MarketEvent


@dataclass
class SimulatedTrade:
    trade_id: str
    token_id: str
    ticker: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    timestamp: float
    execution_delay_ms: float
    slippage: float
    pnl: float = 0.0


class TickSimulator:
    """
    High-fidelity sequential tick-replay simulator.
    Tracks equity curve, latency, order matching, and generates performance metrics.
    """

    def __init__(
        self,
        strategy_class: Type,
        initial_balance: float = 1000.0,
        latency_ms: float = 50.0,  # Simulated network + execution latency
        slippage_pct: float = 0.001,  # 0.1% simulated execution slippage
    ) -> None:
        self.strategy_class = strategy_class
        self.strategy = strategy_class()
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.latency_ms = latency_ms
        self.slippage_pct = slippage_pct

        self.trades: List[SimulatedTrade] = []
        self.equity_curve: List[float] = [initial_balance]
        self._mock_clock: float = 0.0

    async def run_simulation(
        self,
        ticks: List[Dict[str, Any]],
        event_type: str = "last_trade_price",
    ) -> Dict[str, Any]:
        """
        Replay ticks sequentially into the strategy and simulate exchange executions.
        
        Ticks format: [{"token_id": "t1", "price": 0.55, "timestamp": 1716700000}]
        """
        logger.info(f"TickSimulator: Starting simulation with {len(ticks)} ticks...")
        self.trades.clear()
        self.balance = self.initial_balance
        self.equity_curve = [self.initial_balance]

        # Instantiate strategy and ensure its queue consumer task is active
        self.strategy = self.strategy_class()
        if hasattr(self.strategy, "_populate_subscribed_tokens"):
            self.strategy._tokens_populated = True
            if hasattr(self.strategy, "subscribed_tokens"):
                # Proactively populate with test asset IDs from ticks
                self.strategy.subscribed_tokens = {t["token_id"] for t in ticks}
            self.strategy.start_consumer()

        # Intercept record_decision to capture trades executed in async loops
        from unittest.mock import patch

        def mock_record_decision(
            db,
            strategy: str,
            market_ticker: str,
            decision: str,
            confidence: float | None = None,
            signal_data: dict | None = None,
            reason: str | None = None,
        ):
            if decision == "BUY":
                # Convert signal_data to a decision structure
                direction = signal_data.get("direction", "up") if signal_data else "up"
                size_usd = float(signal_data.get("size_usd", 50.0)) if signal_data else 50.0
                entry_price = float(signal_data.get("entry_price", 0.5)) if signal_data else 0.5

                decision_dict = {
                    "token_id": market_ticker,
                    "market_ticker": market_ticker,
                    "decision": "BUY",
                    "direction": direction,
                    "size": size_usd,
                }
                self._match_order(decision_dict, entry_price, self._mock_clock)
            elif decision == "SELL":
                # Position exited during queue processing
                pnl_usd = float(signal_data.get("pnl_usd", 0.0)) if signal_data else 0.0
                exit_price = float(signal_data.get("exit_price", 0.5)) if signal_data else 0.5
                size_usd = float(signal_data.get("size_usd", 50.0)) if signal_data else 50.0

                import uuid
                trade = SimulatedTrade(
                    trade_id=str(uuid.uuid4()),
                    token_id=market_ticker,
                    ticker=market_ticker,
                    side="SELL",
                    price=exit_price,
                    size=size_usd,
                    timestamp=self._mock_clock,
                    execution_delay_ms=self.latency_ms,
                    slippage=0.0,
                    pnl=pnl_usd,
                )
                self.trades.append(trade)
                self.balance += pnl_usd
                self.equity_curve.append(self.balance)

                logger.info(
                    f"TickSimulator: Filled mock exit on {market_ticker} | price={exit_price:.4f} "
                    f"pnl=${pnl_usd:.4f} balance=${self.balance:.2f}"
                )

        # Patch both possible import sites for strategies
        patcher_scalper = patch("backend.strategies.hft_scalper.record_decision", mock_record_decision)
        patcher_maker = patch("backend.strategies.market_maker.record_decision", mock_record_decision)

        patcher_scalper.start()
        patcher_maker.start()

        try:
            # Replay ticks
            for i, tick in enumerate(ticks):
                token_id = tick["token_id"]
                price = float(tick["price"])
                ts = float(tick.get("timestamp") or time.time())
                self._mock_clock = ts

                # Construct type-safe event
                event = MarketEvent(
                    token_id=token_id,
                    event_type=event_type,
                    data={
                        "asset_id": token_id,
                        "price": str(price),
                        "last_trade_price": str(price),
                        "timestamp": ts,
                    },
                    timestamp=ts,
                )

                # Ingest event into strategy
                await self.strategy.on_market_event(event)
                # Allow async task queue loop to run
                await asyncio.sleep(0.005)

            # Force-close any open positions at the end of the simulation to calculate final equity
            if hasattr(self.strategy, "_open_positions"):
                open_positions = list(self.strategy._open_positions.values())
                for pos in open_positions:
                    # Find last price in ticks for this token
                    last_price = 0.5
                    for t in reversed(ticks):
                        if t["token_id"] == pos.ticker:
                            last_price = float(t["price"])
                            break
                    self.strategy._close_position(pos, last_price, "SIM_END_FORCE_CLOSE")
                    pnl = pos.pnl_usd if hasattr(pos, "pnl_usd") else 0.0

                    import uuid
                    trade = SimulatedTrade(
                        trade_id=str(uuid.uuid4()),
                        token_id=pos.market_id,
                        ticker=pos.ticker,
                        side="SELL",
                        price=last_price,
                        size=pos.size_usd,
                        timestamp=self._mock_clock,
                        execution_delay_ms=self.latency_ms,
                        slippage=0.0,
                        pnl=pnl,
                    )
                    self.trades.append(trade)
                    self.balance += pnl
                    self.equity_curve.append(self.balance)
        finally:
            patcher_scalper.stop()
            patcher_maker.stop()

        # Stop consumer loops
        if hasattr(self.strategy, "_consumer_task") and self.strategy._consumer_task:
            self.strategy._consumer_task.cancel()

        return self._generate_report()

    def _match_order(self, decision: Dict[str, Any], market_price: float, ts: float) -> None:
        """Simulate high-fidelity exchange matching, execution delay, and slippage fills."""
        token_id = decision.get("token_id") or decision.get("market_ticker")
        ticker = decision.get("market_ticker", token_id)
        side = decision.get("decision", "BUY")
        direction = decision.get("direction", "up")
        size_usd = float(decision.get("size") or decision.get("suggested_size") or 50.0)

        # 1. Apply simulated execution latency slippage
        # In HFT, executing Buy on "up" (YES) means we buy at slightly worse price (slippage)
        slippage = market_price * self.slippage_pct
        execution_price = market_price + slippage if direction == "up" else market_price - slippage
        execution_price = max(0.01, min(0.99, execution_price))

        import uuid
        trade = SimulatedTrade(
            trade_id=str(uuid.uuid4()),
            token_id=token_id,
            ticker=ticker,
            side=side,
            price=execution_price,
            size=size_usd,
            timestamp=ts,
            execution_delay_ms=self.latency_ms,
            slippage=slippage,
        )

        # For simulated matching in the engine, we record it
        self.trades.append(trade)

        # Deduct cost from balance
        self.balance -= slippage  # deduct execution slippage cost
        self.equity_curve.append(self.balance)

        logger.info(
            f"TickSimulator: Filled mock order on {ticker} | price={execution_price:.4f} "
            f"slippage={slippage:.4f} balance=${self.balance:.2f}"
        )

    def _generate_report(self) -> Dict[str, Any]:
        """Aggregate trade histories and output high-fidelity performance metrics."""
        total_trades = len(self.trades)

        # Calculate win/loss and stats from strategy's closed history if available,
        # otherwise default to mock trades metrics
        closed_stats = {}
        if hasattr(self.strategy, "get_stats"):
            closed_stats = self.strategy.get_stats()

        total_pnl = self.balance - self.initial_balance
        pnl_pct = (total_pnl / self.initial_balance) * 100.0 if self.initial_balance > 0 else 0.0

        win_rate = closed_stats.get("win_rate", 0.5)
        total_wins = closed_stats.get("wins", 0)
        total_losses = closed_stats.get("losses", 0)

        # Sharpe ratio calculation (simplistic over mock trades PnL standard deviation)
        sharpe = 0.0
        if len(self.trades) >= 5:
            import math
            pnls = []
            if hasattr(self.strategy, "_closed_positions"):
                pnls = [p.pnl_usd for p in self.strategy._closed_positions]
            if not pnls:
                pnls = [t.pnl for t in self.trades]

            avg = sum(pnls) / len(pnls)
            variance = sum((x - avg) ** 2 for x in pnls) / len(pnls)
            std_dev = math.sqrt(variance)
            if std_dev > 0:
                sharpe = (avg / std_dev) * math.sqrt(252)  # annualized

        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_pnl_usd": total_pnl,
            "pnl_pct": pnl_pct,
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": win_rate,
            "sharpe_ratio": sharpe,
            "avg_slippage_usd": sum(t.slippage for t in self.trades) / max(total_trades, 1),
            "equity_curve": self.equity_curve,
        }
