"""Flash Crash Reversion Strategy.

Source: homerun open-source repo (production-grade, 102 stars).
Logic: Detect abrupt probability crashes (>8% drop in 240s) and buy
the reversion. Flash crashes in prediction markets are usually
overreactions — prices recover within minutes.

Edge: 5-10% on each reversion trade.
Risk: Some crashes are legitimate (breaking news). Filter with
liquidity and spread constraints to avoid traps.
"""

from datetime import datetime, timezone
from collections import defaultdict

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    StrategyContext,
)
from backend.data.shared_client import get_shared_client
from backend.config import settings

from loguru import logger

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"

# Module-level price history cache: ticker -> [(timestamp, price), ...]
_price_history: dict = defaultdict(list)
_HISTORY_MAX_AGE = 600  # keep 10 minutes of history


class FlashCrashReversionStrategy(BaseStrategy):
    name = "flash_crash_reversion"
    description = "Buy after abrupt probability crashes (>8% drop) when liquidity supports reversion"
    category = "momentum"
    default_params = {
        "lookback_seconds": 240,        # 4-minute lookback window
        "drop_threshold": 0.08,         # 8% minimum drop to trigger
        "min_rebound_fraction": 0.45,   # need 45% of drop recovered
        "max_entry_price": 0.82,        # don't buy if already expensive
        "min_entry_price": 0.10,        # don't buy if too cheap (trap)
        "max_spread": 0.07,             # maximum bid-ask spread
        "min_liquidity": 2500,          # minimum liquidity
        "min_volume": 5000,             # minimum market volume
        "max_position_size": 8.0,
        "max_concurrent": 5,
        "bankroll_pct": 0.04,           # 4% per trade
        "kelly_fraction": 0.25,
        "min_size_usd": 2.0,
        "stop_loss_pct": 0.06,          # 6% stop loss
        "take_profit_pct": 0.12,        # 12% take profit
    }

    async def market_filter(self, markets):
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        client = get_shared_client()

        # Check existing positions
        fc_count = 0
        existing_tickers = set()
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            fc_count = sum(1 for t in open_trades if t.strategy == self.name)
        except Exception:
            pass

        if fc_count >= params["max_concurrent"]:
            return result

        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        # Fetch active markets with volume
        try:
            resp = await client.get(
                GAMMA_API_URL,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 200,
                    "order": "volume",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            markets = resp.json()
        except Exception as e:
            ctx.logger.warning(f"[flash_crash] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            return result

        # Update price history and detect crashes
        for market in markets:
            if fc_count >= params["max_concurrent"]:
                break

            slug = market.get("slug", "")
            if slug in existing_tickers:
                continue

            volume = float(market.get("volume", 0) or 0)
            liquidity = float(market.get("liquidity", 0) or 0)

            if volume < params["min_volume"] or liquidity < params["min_liquidity"]:
                continue

            # Get current best price (highest outcome price)
            outcome_prices = market.get("outcomePrices", [])
            outcomes = market.get("outcomes", [])
            clob_token_ids = market.get("clobTokenIds", [])

            if not outcome_prices or not outcomes:
                continue

            # Find the favorite (highest price) and track it
            best_price = 0
            best_idx = 0
            for i, p_str in enumerate(outcome_prices):
                try:
                    p = float(p_str)
                    if p > best_price:
                        best_price = p
                        best_idx = i
                except (ValueError, TypeError):
                    continue

            if best_price <= 0 or best_price >= 1:
                continue

            # Update price history
            history = _price_history[slug]
            history.append((now_ts, best_price))

            # Prune old entries
            cutoff = now_ts - _HISTORY_MAX_AGE
            _price_history[slug] = [(ts, p) for ts, p in history if ts > cutoff]
            history = _price_history[slug]

            # Need at least a few data points to detect a crash
            if len(history) < 3:
                continue

            # Check for crash: find the highest price in lookback window
            lookback_cutoff = now_ts - params["lookback_seconds"]
            recent_prices = [(ts, p) for ts, p in history if ts > lookback_cutoff]

            if len(recent_prices) < 2:
                continue

            # Find peak and trough in lookback
            peak_price = max(p for _, p in recent_prices)
            trough_price = min(p for _, p in recent_prices)
            current_price = best_price

            # Detect crash: peak dropped significantly
            drop_pct = (peak_price - trough_price) / peak_price if peak_price > 0 else 0

            if drop_pct < params["drop_threshold"]:
                continue

            # Check for rebound: current price should be recovering from trough
            rebound = (current_price - trough_price) / (peak_price - trough_price) if (peak_price - trough_price) > 0 else 0

            if rebound < params["min_rebound_fraction"]:
                continue  # not enough rebound yet, wait

            # Price filters
            if current_price > params["max_entry_price"]:
                continue  # too expensive after rebound
            if current_price < params["min_entry_price"]:
                continue  # too cheap, might be a trap

            # Calculate edge: we expect price to revert toward peak
            # Conservative: target midpoint between current and peak
            target_price = (current_price + peak_price) / 2
            edge = target_price - current_price

            if edge <= 0:
                continue

            # Kelly sizing
            kelly = edge / (1.0 - current_price) if current_price < 1.0 else 0
            size = min(
                params["max_position_size"],
                ctx.bankroll * params["bankroll_pct"],
                ctx.bankroll * kelly * params["kelly_fraction"],
            )
            size = max(size, params["min_size_usd"])
            if size <= 0:
                continue

            # Get token ID
            token_id = ""
            direction = "yes"
            if best_idx < len(clob_token_ids):
                token_id = str(clob_token_ids[best_idx])
            if best_idx < len(outcomes):
                direction = str(outcomes[best_idx]).strip().lower()

            decision = {
                "market_ticker": slug,
                "token_id": token_id,
                "direction": direction,
                "decision": "BUY",
                "entry_price": round(current_price, 4),
                "size": round(size, 2),
                "suggested_size": round(size, 2),
                "edge": round(edge, 4),
                "confidence": round(min(rebound, 0.95), 2),
                "model_probability": round(target_price, 4),
                "market_probability": round(current_price, 4),
                "platform": "polymarket",
                "strategy_name": self.name,
                "stop_loss_pct": params["stop_loss_pct"],
                "take_profit_pct": params["take_profit_pct"],
                "crash_drop_pct": round(drop_pct, 4),
                "rebound_fraction": round(rebound, 4),
                "peak_price": round(peak_price, 4),
                "trough_price": round(trough_price, 4),
            }

            result.decisions.append(decision)
            result.decisions_recorded += 1
            result.trades_attempted += 1
            fc_count += 1

            ctx.logger.info(
                f"[flash_crash] CRASH REVERSION: {slug[:40]} "
                f"peak={peak_price:.3f} trough={trough_price:.3f} "
                f"now={current_price:.3f} drop={drop_pct:.1%} "
                f"rebound={rebound:.1%} edge={edge:.3f} size=${size:.2f}"
            )

        return result
