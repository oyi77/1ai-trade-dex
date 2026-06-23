"""Ultra-cheap NO strategy — bet against ultra-cheap outcomes (<$0.10) exploiting longshot bias.

bond_scanner's best edge: 76.1% WR, +$1,105 from 1,489 settled trades.
Markets overprice longshot outcomes; we bet NO on the cheapest outcome in each market.
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


class UltraCheapNoStrategy(BaseStrategy):
    name = "ultra_cheap_no"
    description = (
        "Bet NO on ultra-cheap outcomes (<$0.10) with high volume — "
        "bond_scanner's best edge (76.1% WR, +$1,105)"
    )
    category = "value"
    PAPER_ONLY = True
    default_params = {
        "min_price": 0.01,
        "max_price": 0.10,
        "min_volume": 500,
        "max_days_to_resolution": 30,
        "min_days_to_resolution": 0,
        "max_position_size": 5.0,
        "max_concurrent": 10,
        "kelly_fraction": 0.25,
        "min_size_usd": 1.0,
        "bankroll_pct": 0.02,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Pass-through: ultra_cheap_no filters by price range in run_cycle."""
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
                1 for t in open_trades if t.strategy == "ultra_cheap_no"
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

            # Parse outcomes and prices
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

            # Find the CHEAPEST outcome (lowest price) in the ultra-cheap range
            cheapest_outcome = None
            cheapest_price = None
            cheapest_index = None

            for i, price_val in enumerate(outcome_prices_raw):
                try:
                    price = float(price_val)
                except (TypeError, ValueError):
                    continue

                if min_price <= price <= max_price:
                    if cheapest_price is None or price < cheapest_price:
                        cheapest_outcome = outcomes[i] if i < len(outcomes) else "yes"
                        cheapest_price = price
                        cheapest_index = i

            if cheapest_price is None:
                continue

            # We have a qualifying market — bet NO on the cheapest outcome
            # E-108: Default to settings bankroll, not hardcoded 100.0
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
            logger.info(
                f"[{self.name}] Using bankroll=${bankroll:.2f} for mode={ctx.mode}"
            )

            # Edge model: longshot bias exploitation for NO bets
            #
            # Cheap outcomes are overpriced due to longshot bias — bettors
            # overpay for lottery-ticket outcomes. We bet NO, collecting the
            # premium. The cheaper the outcome, the stronger the bias.
            #
            # Empirical data (1,489 settled trades): 76.1% WR, +$1,105.
            #
            # Discount model: true probability is lower than market price.
            #   p < 0.05  → 40% discount (true prob = 60% of market)
            #   0.05-0.08 → 25% discount
            #   0.08-0.10 → 15% discount
            if cheapest_price < 0.05:
                longshot_discount = 0.40
            elif cheapest_price < 0.08:
                longshot_discount = 0.25
            else:
                longshot_discount = 0.15

            true_outcome_prob = cheapest_price * (1.0 - longshot_discount)
            true_outcome_prob = max(true_outcome_prob, 0.001)
            # NO wins when the outcome does NOT happen
            win_prob = min(1.0 - true_outcome_prob, 0.995)

            # Fee-adjusted edge for NO bet:
            #   If NO wins: profit = 1.0 - cheapest_price (buy NO at p, redeem at 1.0)
            #   If NO loses: loss = cheapest_price (buy NO at p, redeem at 0.0)
            raw_edge = (
                win_prob * (1.0 - cheapest_price)
                - (1.0 - win_prob) * cheapest_price
            )
            edge = round(raw_edge - 0.001, 4)  # deduct slippage

            # Reject if estimated edge is below min_edge from config
            min_edge_threshold = float(
                params.get(
                    "min_edge",
                    getattr(settings, "BOND_SCANNER_MIN_EDGE", 0.02),
                )
            )
            if edge < min_edge_threshold:
                continue

            # Risk/reward filter: reject if R:R < 2:1
            profit_if_win = 1.0 - cheapest_price
            loss_if_lose = cheapest_price
            rr_ratio = profit_if_win / loss_if_lose if loss_if_lose > 0 else 0
            if rr_ratio < 2.0:
                logger.info(
                    f"[{self.name}] R:R filter: {rr_ratio:.1f}:1 < 2:1 "
                    f"for {market.get('question','')[:40]}"
                )
                continue

            confidence = win_prob

            # Size proportional to edge
            kelly = (
                edge / (1.0 - cheapest_price) if cheapest_price < 1.0 else 0.0
            )
            kelly_fraction = params.get(
                "kelly_fraction", getattr(settings, "KELLY_FRACTION", 0.25)
            )
            size = min(
                max_position_size,
                bankroll * params.get("bankroll_pct", 0.02),
                bankroll * kelly * kelly_fraction,
            )
            size = max(size, params.get("min_size_usd", 1.0))
            size = min(size, max_position_size)

            # Direction is always "no" — we bet against the cheap outcome
            trade_direction = "no"
            trade_entry_price = cheapest_price

            # Use the clob token for the cheapest outcome
            if (
                cheapest_index is not None
                and cheapest_index < len(clob_token_ids)
            ):
                clob_token_id = str(clob_token_ids[cheapest_index])

            # Scale premium by price: ultra-cheap outcomes need more premium
            # to get filled since we're taking the unpopular side
            if cheapest_price < 0.05:
                MARKETABLE_PREMIUM_PCT = 0.03  # 3% for very cheap
            else:
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
            raw_edge = (
                win_prob * profit_if_win - (1.0 - win_prob) * loss_if_lose
            )
            edge = round(raw_edge, 4)
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
                "market_probability": cheapest_price,
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
                        f"UltraCheapNO: {cheapest_outcome} @ {cheapest_price:.2%} | "
                        f"edge={edge:.2%} | {days_to_resolution:.1f}d to resolve"
                    ),
                )
                ctx.db.add(log_row)
            except Exception as e:
                ctx.logger.warning(
                    f"[{self.name}] DecisionLog write failed: {e}"
                )

            # Stop once we'd hit the concurrent limit
            if result.trades_attempted >= (max_concurrent - position_count):
                break

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] DB commit failed: {e}")
            ctx.db.rollback()

        ctx.logger.info(
            f"[{self.name}] Cycle done: {result.decisions_recorded} "
            f"ultra-cheap NO opportunities found"
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
