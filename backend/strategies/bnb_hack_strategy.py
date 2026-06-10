"""
BNB HACK Trading Strategy — Autonomous BSC Spot Trading Agent.

Integrates with PolyEdge scheduler for prediction market + onchain trading.
Runs alongside other strategies in the same execution framework.

Competition: June 22-28, 2026
Strategy: SMA(10/50) trend on 1h BNB/USDT
Capital: $34 USDC on BSC
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, List

from loguru import logger

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.bot.bnb_hack import (
    BnbHackBot,
    BinanceFeed,
    SignalEngine,
    LiveTWAKExchange,
    PaperEngine,
    MetricsCollector,
    BnbHackAlerter,
)
from backend.clients.twak_client import TWAKClient, TWAKConfig
from backend.config import settings


@dataclass
class BnbHackDecision:
    action: str  # "buy", "sell", "hold"
    token: str
    amount: float
    confidence: float
    reason: str


class BnbHackStrategy(BaseStrategy):
    """
    Autonomous Onchain Trading Agent for BSC spot trading.
    
    Runs as a BaseStrategy in PolyEdge scheduler (daily + event-driven).
    Executes SMA crossover trades on BNB/USDT via TWAK.
    """

    name = "bnb_hack"
    description = "BNB HACK — Autonomous Onchain Trading Agent (SMA trend on 1h, BSC spot)"
    category = "onchain_spot"

    def __init__(self):
        super().__init__()
        self._bot: Optional[BnbHackBot] = None
        self._feed: Optional[BinanceFeed] = None
        self._metrics = MetricsCollector()

    async def market_filter(self, markets: List[Dict]) -> List[Dict]:
        """BNB HACK trades BSC spot, not prediction markets."""
        return []

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one signal evaluation cycle and return the decision."""
        try:
            now = datetime.now(timezone.utc)
            is_paper = getattr(ctx, "mode", "paper") == "paper"

            if not is_paper:
                start = datetime.fromisoformat(
                    settings.BNB_HACK_COMPETITION_START.replace("Z", "+00:00"))
                end = datetime.fromisoformat(
                    settings.BNB_HACK_COMPETITION_END.replace("Z", "+00:00"))
                if not (start <= now <= end):
                    return CycleResult(
                        decisions_recorded=0,
                        trades_attempted=0,
                        trades_placed=0,
                    )

            if not self._bot:
                self._feed = BinanceFeed()
                exchange = PaperEngine() if is_paper else LiveTWAKExchange(
                    TWAKClient(TWAKConfig(
                        access_id=settings.TWAK_ACCESS_ID,
                        hmac_secret=settings.TWAK_HMAC_SECRET,
                        wallet_password=settings.TWAK_WALLET_PASSWORD,
                        default_chain="bsc",
                    ))
                )
                self._bot = BnbHackBot(
                    self._feed,
                    SignalEngine(self._feed),
                    exchange,
                    metrics=self._metrics,
                    alerter=BnbHackAlerter(),
                )

            signal = await self._bot.signals.evaluate()
            tick_result = await self._bot.tick()

            result = CycleResult(
                decisions_recorded=1 if signal["action"] != "hold" else 0,
                trades_attempted=1 if signal["action"] != "hold" else 0,
                trades_placed=1 if "buy" in tick_result or "sell" in tick_result else 0,
            )
            result.decisions.append(signal)
            return result

        except Exception as e:
            logger.error("BNB HACK cycle error: {}", e)
            return CycleResult(
                decisions_recorded=0,
                trades_attempted=0,
                trades_placed=0,
                errors=[str(e)],
            )

    async def on_market_event(self, event: Dict) -> Optional[Dict]:
        """Optional: react to real-time market events if subscribed."""
        # BNB HACK is time-based (1h), not event-driven
        # But can be extended for real-time signals later
        return None

    async def cleanup(self):
        """Cleanup on strategy disable."""
        if self._bot:
            await self._bot.close()
            self._bot = None
        if self._feed:
            await self._feed.close()
            self._feed = None
        logger.info("BNB HACK strategy cleaned up")
