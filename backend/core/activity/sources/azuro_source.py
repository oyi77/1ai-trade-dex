"""Azuro activity source — Gnosis Chain on-chain bet events via subgraph."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class AzuroActivitySource(BaseActivitySource):
    """Poll Azuro subgraph for bet creation/resolution events."""

    # GraphQL query for recent bets by bettor address
    _BETS_QUERY = """
    query GetBets($bettor: String!, $first: Int!) {
      bets(
        first: $first
        where: { bettor: $bettor }
        orderBy: createdAt
        orderDirection: desc
      ) {
        id
        bettor
        amount
        payout
        createdAt
        status
        condition {
          conditionId
          outcomes {
            id
            title
          }
        }
        game {
          title
          sport { name }
          league { name }
        }
        outcome { id title }
      }
    }
    """

    def __init__(self, wallet_address: str, azuro_client=None):
        super().__init__(wallet_address, "azuro")
        self._client = azuro_client
        self._seen_bets: set[str] = set()

    async def _run(self):
        if not self._client:
            logger.warning("[azuro] No client provided, skipping activity source")
            return
        self.create_subtask(self.throttled_loop(self._poll_cycle))
        while self._running:
            await asyncio.sleep(1)

    async def _poll_cycle(self):
        """Single iteration of subgraph bet polling."""
        variables = {
            "bettor": self.wallet_address.lower(),
            "first": 50,
        }
        result = await self._client.cached_query(self._BETS_QUERY, variables)
        bets = (result.get("data") or {}).get("bets", [])

        for bet in bets:
            bet_id = bet.get("id", "")
            if bet_id in self._seen_bets:
                continue
            self._seen_bets.add(bet_id)

            status = bet.get("status", "")
            amount = float(bet.get("amount", 0)) / 1e18  # xDAI 18 decimals
            payout = float(bet.get("payout", 0)) / 1e18
            condition = bet.get("condition") or {}
            game = bet.get("game") or {}
            bet.get("outcome") or {}

            # Map bet status to event type
            if status == "Created":
                event_type = "trade_open"
                pnl = None
            elif status in ("Resolved", "Won", "Lost"):
                event_type = "trade_closed"
                pnl = payout - amount if payout > 0 else None
            else:
                event_type = "trade_open"
                pnl = None

            # Build market ticker from game title + condition
            market_ticker = game.get("title", "") or condition.get("conditionId", "")

            event = ActivityEvent(
                source="azuro",
                event_type=event_type,
                wallet_address=self.wallet_address,
                platform="azuro",
                amount=amount,
                token="xDAI",
                tx_hash=bet_id,
                market_ticker=market_ticker,
                side="buy",
                price=round(amount / (payout or amount or 1), 6),
                fee=0.0,
                pnl=pnl,
                raw_data=bet,
            )
            await self._emit(event)
