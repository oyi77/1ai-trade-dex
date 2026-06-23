"""Crypto fade strategy — bet NO on BTC/ETH/crypto markets with cheap outcomes.

Empirical edge: 60.5% win rate, +$1,093 across 1,489 settled trades.
Paper-only: never places real orders.
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

# Crypto keywords to INCLUDE (opposite of bond_scanner which excludes them)
CRYPTO_KEYWORDS = [
    "bitcoin", "btc",
    "ethereum", "eth ",
    "crypto",
    "solana", "sol ",
    "xrp",
    "doge",
]


class BtcFadeStrategy(BaseStrategy):
    name = "btc_fade"
    description = (
        "Fade crypto event outcomes — bet NO on BTC/ETH/crypto markets "
        "with cheap outcomes (60.5% WR, +$1,093)"
    )
    category = "crypto"

    PAPER_ONLY = True

    default_params = {
        "min_price": 0.01,
        "max_price": 0.30,
        "min_volume": 2000,
        "max_days_to_resolution": 14,
        "min_days_to_resolution": 0,
        "max_position_size": 5.0,
        "max_concurrent": 8,
        "kelly_fraction": 0.20,
        "min_size_usd": 1.0,
        "bankroll_pct": 0.02,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Pass-through: btc_fade filters by keywords and price in run_cycle."""
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
            ctx.logger.warning(f"[btc_fade] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            ctx.logger.warning("[btc_fade] Unexpected Gamma API response format")
            return result

        existing_tickers: set[str] = set()
        fade_count = 0
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            existing_tickers |= {t.event_slug for t in open_trades if t.event_slug}
            fade_count = sum(1 for t in open_trades if t.strategy == "btc_fade")
        except Exception as e:
            ctx.logger.warning(f"[btc_fade] Could not query open trades: {e}")

        if fade_count >= max_concurrent:
            ctx.logger.info(
                f"[btc_fade] At max concurrent fades ({fade_count}/{max_concurrent}), skipping cycle"
            )
            return result

        decisions = []

        for market in markets:
            # INCLUDE only crypto markets (opposite of bond_scanner)
            q = (market.get("question") or "").lower()
            if not any(k in q for k in CRYPTO_KEYWORDS):
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

            # Parse clobTokenIds
            clob_token_ids = market.get("clobTokenIds") or []
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except Exception as e:
                    logger.debug(f"Failed to parse clobTokenIds JSON: {e}")
                    clob_token_ids = []

            # Find the NO outcome — we always bet NO
            no_index = None
            no_price = None

            # First, try to find an outcome explicitly named "No"
            for i, outcome in enumerate(outcomes):
                if isinstance(outcome, str) and outcome.strip().lower() == "no":
                    if i < len(outcome_prices_raw):
                        try:
                            no_price = float(outcome_prices_raw[i])
                            no_index = i
                        except (TypeError, ValueError):
                            continue
                    break

            # Fallback: use index 1 (typically the NO token in binary markets)
            if no_index is None and len(outcome_prices_raw) > 1:
                try:
                    no_price = float(outcome_prices_raw[1])
                    no_index = 1
                except (TypeError, ValueError):
                    pass

            if no_price is None:
                continue

            # Price filter — NO token must be in our cheap range
            if no_price < min_price or no_price > max_price:
                continue

            # Get the NO token's clobTokenId
            clob_token_id = None
            if no_index is not None and no_index < len(clob_token_ids):
                clob_token_id = str(clob_token_ids[no_index])
            elif clob_token_ids:
                clob_token_id = str(clob_token_ids[0])

            # --- Bankroll lookup ---
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
                    f"[btc_fade] BotState query failed for mode={ctx.mode}: {e}"
                )

            # --- Edge model ---
            # Crypto markets exhibit longshot bias: cheap NO tokens are
            # underpriced because hype inflates YES. Empirical WR is 60.5%.
            # Edge = our win probability estimate minus market price.
            if no_price < 0.10:
                proximity_boost = 0.08  # strongest longshot bias
            elif no_price < 0.20:
                proximity_boost = 0.06
            else:
                proximity_boost = 0.04

            win_prob = min(no_price + proximity_boost, 0.995)
            raw_edge = (
                win_prob * (1.0 - no_price)
                - (1.0 - win_prob) * no_price
            )
            edge = round(raw_edge - 0.001, 4)  # deduct slippage

            min_edge_threshold = float(
                params.get("min_edge", 0.02)
            )
            if edge < min_edge_threshold:
                continue

            confidence = win_prob

            # --- Position sizing ---
            kelly = edge / (1.0 - no_price) if no_price < 1.0 else 0.0
            kelly_fraction = params.get("kelly_fraction", 0.20)
            size = min(
                max_position_size,
                bankroll * params.get("bankroll_pct", 0.02),
                bankroll * kelly * kelly_fraction,
            )
            size = max(size, params.get("min_size_usd", 1.0))
            size = min(size, max_position_size)

            # Entry price with small premium for marketability
            MARKETABLE_PREMIUM_PCT = float(
                params.get("marketable_premium_pct", 0.02)
            )
            trade_entry_price = min(
                0.99,
                round(no_price * (1.0 + MARKETABLE_PREMIUM_PCT), 4),
            )

            # Recompute edge with actual entry price
            true_win_prob = win_prob
            profit_if_win = 1.0 - trade_entry_price
            loss_if_lose = trade_entry_price
            raw_edge = (
                true_win_prob * profit_if_win
                - (1.0 - true_win_prob) * loss_if_lose
            )
            edge = round(raw_edge, 4)
            if edge < min_edge_threshold:
                continue

            logger.info(
                f"[btc_fade] Sizing: bankroll=${bankroll:.2f} "
                f"max_pos=${max_position_size} kelly={kelly:.4f} "
                f"kf={kelly_fraction} size=${size:.2f}"
            )

            decision = {
                "market_ticker": slug,
                "token_id": clob_token_id,
                "market_question": market.get("question")
                or market.get("title")
                or slug,
                "direction": "no",
                "decision": "BUY",
                "entry_price": trade_entry_price,
                "size": size,
                "suggested_size": size,
                "edge": edge,
                "confidence": confidence,
                "model_probability": min(trade_entry_price + edge, 0.995),
                "market_probability": no_price,
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
                        f"Fade: NO @ {no_price:.2%} | "
                        f"edge={edge:.2%} | {days_to_resolution:.1f}d to resolve"
                    ),
                )
                ctx.db.add(log_row)
            except Exception as e:
                ctx.logger.warning(f"[btc_fade] DecisionLog write failed: {e}")

            # Stop once we'd hit the concurrent limit
            if result.trades_attempted >= (max_concurrent - fade_count):
                break

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[btc_fade] DB commit failed: {e}")
            ctx.db.rollback()

        ctx.logger.info(
            f"[btc_fade] Cycle done: {result.decisions_recorded} fade opportunities found"
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
