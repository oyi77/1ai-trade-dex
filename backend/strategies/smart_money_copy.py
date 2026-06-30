"""Smart Money Copy Trading — follow top Polymarket wallets.

Academic basis: Top 0.03% of Polymarket wallets are consistently profitable.
By copying their trades with a delay filter (<5 min), we ride their edge.

Edge source: Information asymmetry — smart money has better models/data.
"""

from datetime import datetime, timezone, timedelta

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    StrategyContext,
)
from backend.data.shared_client import get_shared_client
from backend.config import settings

from loguru import logger

# Polymarket Data API
LEADERBOARD_URL = "https://data-api.polymarket.com/leaderboard"
TRADES_URL = "https://data-api.polymarket.com/trades"
GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"


class SmartMoneyCopyStrategy(BaseStrategy):
    name = "smart_money_copy"
    description = "Copy trades from top Polymarket wallets with proven track records"
    category = "momentum"
    default_params = {
        "min_wallet_trades": 50,         # minimum trades to qualify
        "min_wallet_win_rate": 0.55,     # minimum win rate
        "min_trade_size": 50.0,          # only copy trades >$50
        "max_trade_age_seconds": 300,    # only copy trades <5 min old
        "max_position_size": 10.0,       # max per trade
        "bankroll_pct": 0.03,            # 3% of bankroll per copy
        "min_size_usd": 2.0,
        "kelly_fraction": 0.25,
        "max_concurrent": 10,
        "top_wallets_count": 30,         # monitor top N wallets
    }

    async def market_filter(self, markets):
        return markets  # we don't filter markets, we filter trades

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}
        client = get_shared_client()

        try:
            # Step 1: Fetch top wallets from leaderboard
            resp = await client.get(
                LEADERBOARD_URL,
                params={"limit": params["top_wallets_count"], "window": "30d"},
            )
            resp.raise_for_status()
            leaderboard = resp.json()

            if not isinstance(leaderboard, list) or not leaderboard:
                ctx.logger.warning("[smart_money_copy] Empty leaderboard")
                return result

            # Step 2: Filter wallets by win rate and trade count
            qualified_wallets = []
            for entry in leaderboard:
                addr = entry.get("address", "")
                trades_count = entry.get("total_trades", 0)
                pnl = entry.get("total_pnl", 0)
                win_rate = entry.get("win_rate", 0)

                if (
                    trades_count >= params["min_wallet_trades"]
                    and win_rate >= params["min_wallet_win_rate"]
                    and pnl > 0
                ):
                    qualified_wallets.append({
                        "address": addr,
                        "win_rate": win_rate,
                        "pnl": pnl,
                        "trades": trades_count,
                    })

            if not qualified_wallets:
                ctx.logger.info("[smart_money_copy] No qualified wallets found")
                return result

            ctx.logger.info(
                f"[smart_money_copy] Found {len(qualified_wallets)} qualified wallets"
            )

            # Step 3: Fetch recent trades from qualified wallets
            now = datetime.now(timezone.utc)
            max_age = timedelta(seconds=params["max_trade_age_seconds"])
            copied_count = 0

            for wallet in qualified_wallets[:10]:  # check top 10
                if copied_count >= params["max_concurrent"]:
                    break

                try:
                    trades_resp = await client.get(
                        TRADES_URL,
                        params={
                            "user": wallet["address"],
                            "limit": 20,
                            "takerOnly": "true",
                        },
                    )
                    trades_resp.raise_for_status()
                    trades = trades_resp.json()

                    if not isinstance(trades, list):
                        continue

                    for trade in trades:
                        if copied_count >= params["max_concurrent"]:
                            break

                        # Filter: recent, large, BUY side
                        trade_size = float(trade.get("size", 0) or 0)
                        trade_side = str(trade.get("side", "")).upper()
                        trade_time_str = trade.get("timestamp", "")

                        if trade_size < params["min_trade_size"]:
                            continue
                        if trade_side != "BUY":
                            continue

                        # Parse timestamp
                        try:
                            trade_time = datetime.fromisoformat(
                                trade_time_str.replace("Z", "+00:00")
                            )
                            if (now - trade_time) > max_age:
                                continue
                        except (ValueError, TypeError):
                            continue

                        # Get market info
                        token_id = trade.get("asset_id", "")
                        market_slug = trade.get("market_slug", "")
                        price = float(trade.get("price", 0) or 0)

                        if not token_id or price <= 0 or price >= 1:
                            continue

                        # Calculate edge based on wallet's historical win rate
                        # If wallet wins 60% and price is 50%, edge = 10%
                        edge = wallet["win_rate"] - price
                        if edge <= 0.01:  # minimum 1% edge
                            continue

                        # Position sizing: fractional Kelly
                        kelly = edge / (1.0 - price) if price < 1.0 else 0
                        size = min(
                            params["max_position_size"],
                            ctx.bankroll * params["bankroll_pct"],
                            ctx.bankroll * kelly * params["kelly_fraction"],
                        )
                        size = max(size, params["min_size_usd"])
                        if size <= 0:
                            continue

                        decision = {
                            "market_ticker": market_slug or token_id,
                            "token_id": token_id,
                            "direction": "yes",
                            "decision": "BUY",
                            "entry_price": round(price, 4),
                            "size": round(size, 2),
                            "suggested_size": round(size, 2),
                            "edge": round(edge, 4),
                            "confidence": round(wallet["win_rate"], 2),
                            "model_probability": round(
                                min(price + edge, 0.995), 4
                            ),
                            "market_probability": round(price, 4),
                            "platform": "polymarket",
                            "strategy_name": self.name,
                            "copy_wallet": wallet["address"][:10],
                        }

                        result.decisions.append(decision)
                        result.decisions_recorded += 1
                        result.trades_attempted += 1
                        copied_count += 1

                        ctx.logger.info(
                            f"[smart_money_copy] Copying {wallet['address'][:10]}... "
                            f"WR={wallet['win_rate']:.0%} | {market_slug[:40]} "
                            f"@ {price:.3f} edge={edge:.3f} size=${size:.2f}"
                        )

                except Exception as e:
                    ctx.logger.debug(
                        f"[smart_money_copy] Error fetching trades for {wallet['address'][:10]}: {e}"
                    )

        except Exception as e:
            ctx.logger.error(f"[smart_money_copy] Cycle error: {e}")
            result.errors.append(str(e))

        return result
