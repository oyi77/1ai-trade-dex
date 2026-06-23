"""Mid-Range NO Strategy — bet against outcomes priced $0.30-0.50.

Based on edge analysis of 1,489 settled trades:
- NO bets on mid-range outcomes ($0.30-0.50): 98.5% WR, +$696
- The market overprices mid-range outcomes; the NO side captures that edge.
- Paper-only while the edge model is validated forward.
"""

from datetime import datetime, timezone

import json

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.data.shared_client import get_shared_client
from backend.config import settings

from loguru import logger

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"


class MidRangeNoStrategy(BaseStrategy):
    name = "mid_range_no"
    description = (
        "Bet NO on mid-range outcomes ($0.30-0.50) — longshot_bias's real edge "
        "(98.5% WR, +$696)"
    )
    category = "value"
    PAPER_ONLY = True

    default_params = {
        "min_price": 0.30,
        "max_price": 0.50,
        "min_volume": 1000,
        "max_days_to_resolution": 60,
        "min_days_to_resolution": 0,
        "max_position_size": 5.0,
        "max_concurrent": 10,
        "kelly_fraction": 0.25,
        "min_size_usd": 1.0,
        "bankroll_pct": 0.02,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Pass-through: mid_range_no filters by price range in run_cycle."""
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)

        params = {**self.default_params, **(ctx.params or {})}

        # Check open positions for auto-sell exits at cycle start
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell

            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(
                    params.get(
                        "auto_sell_profit_target_pct",
                        params.get("profit_target_pct", 0.025),
                    )
                ),
                stop_loss_pct=float(
                    params.get(
                        "auto_sell_stop_loss_pct", params.get("stop_loss_pct", 0.03)
                    )
                ),
                max_hold_seconds=int(
                    params.get(
                        "auto_sell_max_hold_seconds",
                        params.get("max_hold_seconds", 120),
                    )
                ),
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Auto-sell start check failed: {e}")

        min_price = float(params["min_price"])
        max_price = float(params["max_price"])
        min_volume = float(params["min_volume"])
        max_days = float(params["max_days_to_resolution"])
        min_days = float(params["min_days_to_resolution"])
        max_position_size = float(params["max_position_size"])
        max_concurrent = int(params["max_concurrent"])

        now = datetime.now(timezone.utc)

        # Fetch active markets sorted by volume
        try:
            client = get_shared_client()
            resp = await client.get(
                GAMMA_API_URL,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 500,
                    "order": "volume",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            markets = resp.json()
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            ctx.logger.warning(f"[{self.name}] Unexpected Gamma API response format")
            return result

        existing_tickers: set[str] = set()
        position_count = 0
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            existing_tickers |= {t.event_slug for t in open_trades if t.event_slug}
            position_count = sum(
                1 for t in open_trades if t.strategy == "mid_range_no"
            )
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] Could not query open trades: {e}")

        if position_count >= max_concurrent:
            ctx.logger.info(
                f"[{self.name}] At max concurrent ({position_count}/{max_concurrent}), skipping cycle"
            )
            return result

        decisions = []

        for market in markets:
            # Skip risky markets (oil, crypto, stocks) — only weather/sports/politics
            q = (market.get("question") or "").lower()
            RISKY_KEYWORDS = [
                "wti", "oil", "crude", "brent", "solana", "sol ", "bitcoin", "btc",
                "ethereum", "eth ", "crypto", "xrp", "doge", "stock", "earnings",
                "macy", "tesla", "apple", "nvidia", "market cap", "price of",
            ]
            if any(k in q for k in RISKY_KEYWORDS):
                continue

            # Volume filter
            volume = float(market.get("volume", 0) or 0)
            if volume < min_volume:
                continue

            # Resolution date filter
            end_date_str = (
                market.get("endDate")
                or market.get("end_date_iso")
                or market.get("endDateIso")
            )
            if not end_date_str:
                continue

            try:
                end_date_str_clean = end_date_str.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(end_date_str_clean)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            days_to_resolution = (end_dt - now).total_seconds() / 86400.0
            if days_to_resolution > max_days or days_to_resolution < min_days:
                continue

            # Skip if we already hold a position
            slug = market.get("slug") or market.get("conditionId") or ""
            if slug in existing_tickers:
                continue

            clob_token_id = None
            clob_token_ids = market.get("clobTokenIds") or []
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except Exception as e:
                    logger.debug(f"Failed to parse clobTokenIds JSON: {e}")
                    clob_token_ids = []
            if clob_token_ids and len(clob_token_ids) > 0:
                clob_token_id = str(clob_token_ids[0])

            # Price filter — check outcomePrices for mid-range outcomes
            outcome_prices_raw = market.get("outcomePrices") or []
            outcomes = market.get("outcomes") or []

            if isinstance(outcome_prices_raw, str):
                try:
                    outcome_prices_raw = json.loads(outcome_prices_raw)
                except Exception as e:
                    logger.debug(f"Failed to parse outcomePrices JSON: {e}")
                    continue

            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except Exception as e:
                    logger.debug(f"Failed to parse outcomes JSON: {e}")
                    outcomes = []

            if not outcome_prices_raw:
                continue

            qualifying_outcome = None
            qualifying_price = None
            qualifying_index = None

            for i, price_val in enumerate(outcome_prices_raw):
                try:
                    price = float(price_val)
                except (TypeError, ValueError):
                    continue

                if min_price <= price <= max_price:
                    qualifying_outcome = outcomes[i] if i < len(outcomes) else "yes"
                    qualifying_price = price
                    qualifying_index = i
                    break

            if qualifying_price is None:
                continue

            # --- Mid-Range NO Edge Model ---
            # We bet NO on the qualifying outcome (priced 0.30-0.50).
            # The NO token costs: no_token_price = 1 - qualifying_price (0.50-0.70).
            #
            # Empirical edge from 1,489 settled trades: 98.5% WR, +$696.
            # Conservative model: true_win_prob = 1 - qualifying_price + 0.10
            #   - At 0.30: true_win_prob = 0.80, edge ≈ 10%
            #   - At 0.50: true_win_prob = 0.60, edge ≈ 10%
            # This is conservative vs the empirical 98.5% WR.

            no_token_price = round(1.0 - qualifying_price, 4)
            true_win_prob = min(1.0 - qualifying_price + 0.10, 0.95)

            # Edge: EV of buying NO token
            # Win → profit = 1 - no_token_price = qualifying_price
            # Lose → loss = no_token_price
            edge = round(
                true_win_prob * qualifying_price
                - (1.0 - true_win_prob) * no_token_price,
                4,
            )

            min_edge_threshold = float(
                params.get("min_edge", getattr(settings, "MID_RANGE_NO_MIN_EDGE", 0.05))
            )
            if edge < min_edge_threshold:
                continue

            # Risk/reward: win = qualifying_price, loss = no_token_price
            rr_ratio = (
                qualifying_price / no_token_price if no_token_price > 0 else 0
            )
            if rr_ratio < 1.5:
                continue

            confidence = true_win_prob

            # Bankroll lookup
            bankroll = (
                float(ctx.settings.INITIAL_BANKROLL)
                if hasattr(ctx.settings, "INITIAL_BANKROLL")
                else 1000.0
            )
            try:
                from backend.models.database import BotState, for_update

                state = for_update(
                    ctx.db, ctx.db.query(BotState).filter_by(mode=ctx.mode)
                ).first()
                if state:
                    if ctx.mode == "paper":
                        bankroll = float(
                            state.paper_bankroll
                            if state.paper_bankroll is not None
                            else ctx.settings.INITIAL_BANKROLL
                        )
                    elif ctx.mode == "testnet":
                        bankroll = float(
                            state.testnet_bankroll
                            if state.testnet_bankroll is not None
                            else ctx.settings.INITIAL_BANKROLL
                        )
                    else:
                        bankroll = float(
                            state.bankroll
                            if state.bankroll is not None
                            else ctx.settings.INITIAL_BANKROLL
                        )
            except Exception as e:
                logger.warning(
                    f"[{self.name}] BotState query failed for mode={ctx.mode}: {e}"
                )

            # Kelly sizing: kelly = edge / (profit_if_win) = edge / qualifying_price
            kelly = edge / qualifying_price if qualifying_price > 0 else 0.0
            kelly_fraction = float(params["kelly_fraction"])
            size = min(
                max_position_size,
                bankroll * float(params["bankroll_pct"]),
                bankroll * kelly * kelly_fraction,
            )
            size = max(size, float(params["min_size_usd"]))
            size = min(size, max_position_size)

            # Direction is always "no" — we bet against the mid-range outcome
            trade_direction = "no"

            # The NO token is the opposite of the qualifying outcome.
            # clobTokenIds: [YES_id, NO_id]. If qualifying_index is 0 (YES),
            # the NO token is at index 1. If qualifying_index is 1 (NO),
            # the NO token is at index 1 (it's already the NO token).
            no_token_index = 1 if qualifying_index == 0 else qualifying_index
            if no_token_index < len(clob_token_ids):
                clob_token_id = str(clob_token_ids[no_token_index])

            # Entry price is the NO token price
            trade_entry_price = no_token_price

            # Marketable premium for fill probability
            MARKETABLE_PREMIUM_PCT = float(
                params.get("marketable_premium_pct", 0.02)
            )
            trade_entry_price = min(
                0.99,
                round(trade_entry_price * (1.0 + MARKETABLE_PREMIUM_PCT), 4),
            )

            # Recompute edge with actual entry price
            profit_if_win = 1.0 - trade_entry_price
            loss_if_lose = trade_entry_price
            edge = round(
                true_win_prob * profit_if_win - (1.0 - true_win_prob) * loss_if_lose,
                4,
            )
            if edge < min_edge_threshold:
                continue

            logger.info(
                f"[{self.name}] Sizing: bankroll=${bankroll:.2f} "
                f"max_pos=${max_position_size} kelly={kelly:.4f} "
                f"kf={kelly_fraction} size=${size:.2f}"
            )

            decision = {
                "market_ticker": slug,
                "token_id": clob_token_id,
                "market_question": market.get("question")
                or market.get("title")
                or slug,
                "direction": trade_direction,
                "decision": "BUY",
                "entry_price": trade_entry_price,
                "size": size,
                "suggested_size": size,
                "edge": edge,
                "confidence": confidence,
                "model_probability": min(trade_entry_price + edge, 0.995),
                "market_probability": qualifying_price,
                "platform": settings.DEFAULT_VENUE,
                "strategy_name": self.name,
                "days_to_resolution": round(days_to_resolution, 2),
                "market_end_date": end_date_str,
                "volume": volume,
            }
            decisions.append(decision)
            result.decisions.append(decision)

            result.decisions_recorded += 1
            result.trades_attempted += 1

            # Log decision
            try:
                from backend.models.database import DecisionLog

                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=slug[:64] if slug else "unknown",
                    decision="BUY",
                    confidence=confidence,
                    signal_data=json.dumps(decision),
                    reason=(
                        f"Mid-Range NO: {qualifying_outcome} @ {qualifying_price:.2%} | "
                        f"NO token @ {no_token_price:.2%} | "
                        f"edge={edge:.2%} | {days_to_resolution:.1f}d to resolve"
                    ),
                )
                ctx.db.add(log_row)
            except Exception as e:
                ctx.logger.warning(f"[{self.name}] DecisionLog write failed: {e}")

            # Stop once we'd hit the concurrent limit
            if result.trades_attempted >= (max_concurrent - position_count):
                break

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] DB commit failed: {e}")
            ctx.db.rollback()

        ctx.logger.info(
            f"[{self.name}] Cycle done: {result.decisions_recorded} mid-range NO opportunities found"
        )

        # Check open positions for auto-sell exits at cycle end
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell

            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(
                    params.get(
                        "auto_sell_profit_target_pct",
                        params.get("profit_target_pct", 0.025),
                    )
                ),
                stop_loss_pct=float(
                    params.get(
                        "auto_sell_stop_loss_pct", params.get("stop_loss_pct", 0.03)
                    )
                ),
                max_hold_seconds=int(
                    params.get(
                        "auto_sell_max_hold_seconds",
                        params.get("max_hold_seconds", 120),
                    )
                ),
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Auto-sell end check failed: {e}")

        return result
