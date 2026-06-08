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
from typing import Optional, Dict, Any, List
import csv
from pathlib import Path

from loguru import logger

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.bot.bnb_hack import (
    BnbHackBot,
    BinanceFeed,
    SignalEngine,
    LiveTWAKExchange,
    PaperEngine,
    BotState,
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
        self._paper_mode = not settings.BNB_HACK_COMPETITION_START  # Fallback to paper if no config

    async def market_filter(self, markets: List[Dict]) -> List[Dict]:
        """Filter markets — we don't use market provider, we trade BSC directly."""
        return []  # BNB HACK doesn't participate in market-based filtering

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """
        Execute one strategy cycle: evaluate signal, manage position, execute trade.
        Called by PolyEdge scheduler (default: daily, can be more frequent).
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Check competition window
            start = datetime.fromisoformat(
                settings.BNB_HACK_COMPETITION_START.replace("Z", "+00:00"))
            end = datetime.fromisoformat(
                settings.BNB_HACK_COMPETITION_END.replace("Z", "+00:00"))
            
            if not (start <= now <= end):
                return CycleResult(
                    timestamp=now,
                    signal="idle",
                    decision={},
                    confidence=0.0,
                    reason=f"Outside competition window ({start} to {end})",
                    error=None,
                )

            # Initialize bot on first cycle
            if not self._bot:
                self._feed = BinanceFeed()
                config = TWAKConfig(
                    access_id=settings.TWAK_ACCESS_ID,
                    hmac_secret=settings.TWAK_HMAC_SECRET,
                    wallet_password=settings.TWAK_WALLET_PASSWORD,
                    default_chain="bsc",
                )
                exchange = (
                    PaperEngine() if self._paper_mode 
                    else LiveTWAKExchange(TWAKClient(config))
                )
                self._bot = BnbHackBot(
                    self._feed,
                    SignalEngine(self._feed),
                    exchange,
                    metrics=self._metrics,
                    alerter=BnbHackAlerter(),
                )

            # Run one tick
            tick_result = await self._bot.tick()
            signal = await self._bot.signals.evaluate()
            
            # Build cycle result
            decision = {
                "action": signal["action"],
                "token": "BNB",
                "confidence": signal["confidence"],
                "reason": signal["reason"],
            }
            
            return CycleResult(
                timestamp=now,
                signal=signal["action"],
                decision=decision,
                confidence=signal["confidence"],
                reason=tick_result,
                error=None,
            )

        except Exception as e:
            logger.error("BNB HACK cycle error: {}", e)
            return CycleResult(
                timestamp=datetime.now(timezone.utc),
                signal="error",
                decision={},
                confidence=0.0,
                reason=str(e),
                error=str(e),
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
