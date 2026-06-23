"""APEX signal pipeline — convert raw edges into actionable trade signals.

Pipeline stages:
1. Filter: remove edges below min_edge_pp, expired edges, low confidence
2. Deduplicate: same market from multiple scanners → keep highest edge_score
3. Size: Kelly fraction * confidence discount * bankroll
4. Rank: sort by expected_value = edge_pp * size_usd
"""

from __future__ import annotations

from typing import List

from loguru import logger

from backend.config import _cfg
from backend.core.edge.edge_model import Edge, Signal


class SignalPipeline:
    """Convert raw Edge objects into tradeable signals."""

    def __init__(self) -> None:
        self.min_edge_pp = float(_cfg("APEX_MIN_EDGE_PP", 0.005))
        self.min_confidence = float(_cfg("APEX_MIN_CONFIDENCE", 0.3))
        self.kelly_fraction = float(_cfg("APEX_KELLY_FRACTION", 0.25))
        self.max_bankroll_pct = float(_cfg("APEX_BANKROLL_PCT", 0.08))
        self.min_size_usd = float(_cfg("MIN_ORDER_USDC", 1.0))
        self.profit_target_pct = float(_cfg("APEX_PROFIT_TARGET_PCT", 0.025))
        self.stop_loss_pct = float(_cfg("APEX_STOP_LOSS_PCT", 0.03))
        self.max_hold_seconds = int(_cfg("APEX_MAX_HOLD_SECONDS", 7200))
        self.max_signals = int(_cfg("APEX_MAX_CONCURRENT", 5))

    async def evaluate(self, edges: List[Edge], ctx) -> List[Signal]:
        """Filter, deduplicate, size, and rank edges into actionable signals.

        Also enriches edges with historical calibration mispricing detection.
        """
        if not edges:
            return []

        # Stage 0: Enrich with historical edge detection
        try:
            from backend.core.edge.historical_edge_detector import get_historical_edge_detector
            detector = get_historical_edge_detector()
            # Only run for markets without existing structural edges
            if len(edges) < 3:
                hist_edges = detector.detect(
                    market_question=getattr(ctx, "market_question", ""),
                    market_price=getattr(ctx, "market_price", 0.5),
                    category=getattr(ctx, "category", ""),
                )
                edges = edges + hist_edges
        except Exception:
            logger.debug("[apex:pipeline] Historical edge detection skipped")

        # Stage 1: Filter
        filtered = self._filter(edges)
        logger.debug(f"[apex:pipeline] Filter: {len(edges)} → {len(filtered)} edges")

        # Stage 2: Deduplicate
        deduped = self._deduplicate(filtered)
        logger.debug(f"[apex:pipeline] Dedup: {len(filtered)} → {len(deduped)} edges")

        # Stage 3: Size (with anti-martingale)
        bankroll = self._get_bankroll(ctx)
        strategy_name = getattr(ctx, "strategy_name", "")
        signals = self._size(deduped, bankroll, strategy_name)
        logger.debug(f"[apex:pipeline] Sized: {len(deduped)} edges → {len(signals)} signals")

        # Stage 4: Rank and cap
        ranked = self._rank(signals)
        capped = ranked[: self.max_signals]
        logger.info(
            f"[apex:pipeline] {len(edges)} edges → {len(capped)} signals "
            f"(bankroll=${bankroll:.2f})"
        )

        return capped

    def _filter(self, edges: List[Edge]) -> List[Edge]:
        """Remove edges below thresholds or expired."""
        filtered = []
        for edge in edges:
            # Expired edges
            if edge.is_expired:
                logger.debug(f"[apex:pipeline] Expired: {edge.market_id} {edge.edge_type.value}")
                continue
            # Minimum edge
            if edge.edge_pp < self.min_edge_pp:
                logger.debug(
                    f"[apex:pipeline] Low edge: {edge.market_id} "
                    f"edge_pp={edge.edge_pp:.4f} < {self.min_edge_pp}"
                )
                continue
            # Minimum confidence
            if edge.confidence < self.min_confidence:
                logger.debug(
                    f"[apex:pipeline] Low confidence: {edge.market_id} "
                    f"conf={edge.confidence:.2f} < {self.min_confidence}"
                )
                continue
            filtered.append(edge)
        return filtered

    def _deduplicate(self, edges: List[Edge]) -> List[Edge]:
        """Keep highest edge_score for each (market_id, direction)."""
        seen: dict[str, Edge] = {}
        for edge in edges:
            key = f"{edge.market_id}:{edge.direction}"
            if key not in seen or edge.edge_score > seen[key].edge_score:
                seen[key] = edge
        return sorted(seen.values(), key=lambda e: e.edge_score, reverse=True)

    def _rank(self, signals: List[Signal]) -> List[Signal]:
        """Rank signals by expected value (edge_pp * size)."""
        return sorted(signals, key=lambda s: s.expected_value, reverse=True)

    def _get_bankroll(self, ctx) -> float:
        """Get current bankroll from context."""
        try:
            from backend.models.database import BotState, for_update
            state = for_update(
                ctx.db, ctx.db.query(BotState).filter(BotState.mode == ctx.mode)
            ).first()
            if state:
                if ctx.mode == "paper":
                    value = state.paper_bankroll
                elif ctx.mode == "testnet":
                    value = state.testnet_bankroll
                else:
                    value = state.bankroll
                if value is not None:
                    return max(0.0, float(value))
        except Exception as e:
            logger.debug(f"[apex:pipeline] Bankroll query failed: {e}")
        return float(_cfg("INITIAL_BANKROLL", 20.0))

    def _size(self, edges: List[Edge], bankroll: float, strategy_name: str = "") -> List[Signal]:
        """Calculate position sizes using quarter-Kelly with confidence discount.

        Anti-martingale: if strategy has 3+ consecutive losses, halve position size.
        Hard cap: max 2% of bankroll per trade regardless of Kelly output.
        """
        signals = []

        # Check for losing streak (anti-martingale)
        loss_streak = 0
        if strategy_name:
            try:
                from backend.models.database import Trade
                from backend.db.utils import get_db_session
                with get_db_session() as db:
                    recent = (
                        db.query(Trade.result)
                        .filter(
                            Trade.strategy == strategy_name,
                            Trade.settled.is_(True),
                            Trade.result.isnot(None),
                        )
                        .order_by(Trade.settlement_time.desc())
                        .limit(10)
                        .all()
                    )
                    for r in recent:
                        if r.result == "loss":
                            loss_streak += 1
                        else:
                            break
            except Exception:
                pass

        anti_martingale_mult = 0.5 if loss_streak >= 3 else 1.0
        if anti_martingale_mult < 1.0:
            logger.info(
                f"[apex:pipeline] Anti-martingale: {strategy_name} has {loss_streak} "
                f"consecutive losses → sizing at {anti_martingale_mult:.0%}"
            )

        # Hard cap: 2% of bankroll
        max_bet_pct = 0.02

        for edge in edges:
            if edge.direction in ("yes", "up"):
                kelly = edge.edge_pp / (1.0 - edge.entry_price) if edge.entry_price < 0.99 else 0.0
            else:
                kelly = edge.edge_pp / edge.entry_price if edge.entry_price > 0.01 else 0.0

            kelly = max(0, kelly)
            size_usd = min(
                bankroll * max_bet_pct,  # hard cap at 2% bankroll
                bankroll * self.max_bankroll_pct,  # configurable max position size
                bankroll * kelly * self.kelly_fraction * edge.confidence,  # Kelly-sized
            )
            size_usd *= anti_martingale_mult  # apply anti-martingale discount
            size_usd = max(size_usd, self.min_size_usd)

            if size_usd < self.min_size_usd:
                continue

            ev = edge.edge_pp * size_usd

            signal = Signal(
                market_id=edge.market_id,
                token_id=edge.token_id,
                edge_type=edge.edge_type,
                direction=edge.direction,
                entry_price=edge.entry_price,
                fair_price=edge.fair_price,
                edge_pp=edge.edge_pp,
                confidence=edge.confidence,
                edge_score=edge.edge_score,
                size_usd=round(size_usd, 2),
                expected_value=round(ev, 4),
                time_horizon_min=edge.time_horizon_min,
                profit_target_pct=self.profit_target_pct,
                stop_loss_pct=self.stop_loss_pct,
                max_hold_seconds=self.max_hold_seconds,
                source_edges=[edge],
                metadata=edge.metadata,
            )
            signals.append(signal)

        return signals