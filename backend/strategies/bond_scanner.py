"""High-probability bond scanner — buy near-certain outcomes for guaranteed-ish returns."""
from datetime import datetime, timezone

import httpx

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.config import settings

from loguru import logger
GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"


class BondScannerStrategy(BaseStrategy):
    name = "bond_scanner"
    description = (
        "Buy high-probability outcomes (>85c) near resolution for low-risk returns"
    )
    category = "value"
    default_params = {
        "min_price": settings.BOND_SCANNER_MIN_PRICE,
        "max_price": settings.BOND_SCANNER_MAX_PRICE,
        "min_volume": settings.BOND_SCANNER_MIN_VOLUME,
        "max_days_to_resolution": settings.BOND_SCANNER_MAX_DAYS_TO_RESOLUTION,
        "min_days_to_resolution": settings.BOND_SCANNER_MIN_DAYS_TO_RESOLUTION,
        "max_position_size": settings.BOND_SCANNER_MAX_POSITION_SIZE,
        "max_concurrent_bonds": settings.BOND_SCANNER_MAX_CONCURRENT_BONDS,
        "kelly_fraction": settings.BOND_SCANNER_KELLY_FRACTION,
        "min_size_usd": settings.BOND_SCANNER_MIN_SIZE_USD,
        "bankroll_pct": settings.BOND_SCANNER_BANKROLL_PCT,
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to bond-relevant markets (treasury, interest rate, fed, bond keywords)."""
        bond_keywords = {
            "bond",
            "treasury",
            "interest rate",
            "fed",
            "yield",
            "debt ceiling",
            "t-bill",
        }
        filtered = [
            m for m in markets if any(kw in m.question.lower() for kw in bond_keywords)
        ]
        # If no keyword matches, fall back to base class DB-driven filter
        if not filtered:
            return await super().market_filter(markets)
        return filtered

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)

        params = {**self.default_params, **(ctx.params or {})}
        min_price = float(params["min_price"])
        max_price = float(params["max_price"])
        min_volume = float(params["min_volume"])
        max_days = float(params["max_days_to_resolution"])
        min_days = float(params["min_days_to_resolution"])
        max_position_size = float(params["max_position_size"])
        max_concurrent = int(params["max_concurrent_bonds"])

        now = datetime.now(timezone.utc)

        # Fetch active markets sorted by volume
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    GAMMA_API_URL,
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": 100,
                        "order": "volume",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                markets = resp.json()
        except Exception as e:
            ctx.logger.warning(f"[bond_scanner] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            ctx.logger.warning("[bond_scanner] Unexpected Gamma API response format")
            return result

        existing_tickers: set[str] = set()
        bond_count = 0
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            existing_tickers |= {t.event_slug for t in open_trades if t.event_slug}
            bond_count = sum(
                1 for t in open_trades if t.strategy == "bond_scanner"
            )
        except Exception as e:
            ctx.logger.warning(f"[bond_scanner] Could not query open trades: {e}")

        if bond_count >= max_concurrent:
            ctx.logger.info(
                f"[bond_scanner] At max concurrent bonds ({bond_count}/{max_concurrent}), skipping cycle"
            )
            return result

        decisions = []

        for market in markets:
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
                # Parse ISO date; handle trailing Z
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
                import json as _json

                try:
                    clob_token_ids = _json.loads(clob_token_ids)
                except Exception as e:
                    logger.debug(f"Failed to parse clobTokenIds JSON: {e}")
                    clob_token_ids = []
            if clob_token_ids and len(clob_token_ids) > 0:
                clob_token_id = str(clob_token_ids[0])

            # Price filter — check outcomePrices
            outcome_prices_raw = market.get("outcomePrices") or []
            outcomes = market.get("outcomes") or []

            # outcomePrices and outcomes may be JSON strings or lists
            if isinstance(outcome_prices_raw, str):
                import json as _json

                try:
                    outcome_prices_raw = _json.loads(outcome_prices_raw)
                except Exception as e:
                    logger.debug(f"Failed to parse outcomePrices JSON: {e}")
                    continue

            if isinstance(outcomes, str):
                import json as _json

                try:
                    outcomes = _json.loads(outcomes)
                except Exception as e:
                    logger.debug(f"Failed to parse outcomes JSON: {e}")
                    outcomes = []

            if not outcome_prices_raw:
                continue

            qualifying_outcome = None
            qualifying_price = None

            for i, price_val in enumerate(outcome_prices_raw):
                try:
                    price = float(price_val)
                except (TypeError, ValueError):
                    continue

                if min_price <= price <= max_price:
                    qualifying_outcome = outcomes[i] if i < len(outcomes) else "yes"
                    qualifying_price = price
                    break

            if qualifying_price is None:
                continue

            # We have a qualifying market
            # E-108: Default to settings bankroll, not hardcoded 100.0
            bankroll = float(ctx.settings.INITIAL_BANKROLL) if hasattr(ctx.settings, 'INITIAL_BANKROLL') else 1000.0
            try:
                from backend.models.database import BotState, for_update

                state = for_update(ctx.db, ctx.db.query(BotState)).first()
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
                logger.debug(f"Failed to query open trades: {e}")

            # Conservative edge model:
            # Assume the market is efficient at pricing probabilities above 0.90.
            # Our edge comes from the natural bias: markets slightly underprice
            # high-probability outcomes close to resolution (last 1-10 days)
            # because liquidity providers want to exit. Cap our assumed boost
            # conservatively so that a single loss doesn't wipe many wins.
            #
            # Key constraint: risk/reward ratio.
            # At price=P, profit_if_win = (1-P)*size, loss_if_lose = P*size
            # Require: win_prob * (1-P) - (1-win_prob) * P > 0
            # i.e. win_prob > P  (we need to believe the TRUE prob exceeds market)
            #
            # Conservative boost: 1% for markets at 0.92, tapering to 0.5% at 0.98
            taper = max(0.0, (qualifying_price - 0.92) / 0.06)  # 0 at 0.92, 1 at 0.98
            proximity_boost = 0.01 * (1.0 - 0.5 * taper)  # 1% at 0.92, 0.5% at 0.98
            win_prob = min(qualifying_price + proximity_boost, 0.97)
            edge = round(
                win_prob * (1.0 - qualifying_price)
                - (1.0 - win_prob) * qualifying_price,
                4,
            )
            # Reject if estimated edge is below min_edge from config
            if edge < 0.005:
                continue
            confidence = win_prob
            # Size proportional to edge — don't max-bet on tiny edges
            kelly = edge / (1.0 - qualifying_price) if qualifying_price < 1.0 else 0.0
            kelly_fraction = params.get("kelly_fraction", 0.25)
            size = min(max_position_size, bankroll * params.get("bankroll_pct", 0.08), bankroll * kelly * kelly_fraction)
            size = max(size, params.get("min_size_usd", 5.0))
            size = min(size, max_position_size)

            trade_direction = str(qualifying_outcome).strip().strip("'\"").lower()
            if trade_direction not in ("yes", "no", "up", "down"):
                # If outcome name is not a valid direction, default to YES for prediction markets
                trade_direction = "yes"
            # entry_price must reflect the cost of the share we're buying.
            # qualifying_price is the YES outcome price.
            # If betting NO, the share cost is (1 - qualifying_price).
            if trade_direction in ("no", "down"):
                trade_entry_price = round(1.0 - qualifying_price, 6)
            else:
                trade_entry_price = qualifying_price

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
                "model_probability": qualifying_price,
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
                import json as _json

                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=slug[:64] if slug else "unknown",
                    decision="BUY",
                    confidence=confidence,
                    signal_data=_json.dumps(decision),
                    reason=(
                        f"Bond: {qualifying_outcome} @ {qualifying_price:.2%} | "
                        f"edge={edge:.2%} | {days_to_resolution:.1f}d to resolve"
                    ),
                )
                ctx.db.add(log_row)
            except Exception as e:
                ctx.logger.warning(f"[bond_scanner] DecisionLog write failed: {e}")

            # Stop once we'd hit the concurrent limit
            if result.trades_attempted >= (max_concurrent - bond_count):
                break

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[bond_scanner] DB commit failed: {e}")
            ctx.db.rollback()

        ctx.logger.info(
            f"[bond_scanner] Cycle done: {result.decisions_recorded} bond opportunities found"
        )
        return result
