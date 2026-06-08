"""Resolution Sniper — buy near-certain crypto 5-min binary outcomes close to resolution.

Edge: when BTC/ETH/SOL price is clearly above/below the strike with 2+ minutes
until resolution, the market is slow to reprice the obvious outcome.  Buy the
near-certain side at 93-97c, collect the settlement at $1.

Distinct from cex_pm_leadlag (momentum on 50/50 markets) and bond_scanner
(generic high-prob outcomes over days).  This targets *crypto 5-min binaries*
with price-distance certainty.
"""

from datetime import datetime, timezone

import json
import re

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.data.shared_client import get_shared_client
from backend.data.crypto import compute_crypto_microstructure
from backend.config import settings

from loguru import logger

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"

# Supported asset prefixes in market questions
_ASSET_PAIRS = {
    "btc": ("bitcoin", "BTCUSDT"),
    "eth": ("ethereum", "ETHUSDT"),
    "sol": ("solana", "SOLUSDT"),
}

# Regex to parse strike price from questions like:
#   "Will BTC be above $67,500 at 10:05?"
#   "Will the price of ETH be above $3,200.50 at 4:15pm?"
_STRIKE_RE = re.compile(
    r"(?:above|below|over|under)\s*\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _parse_strike(question: str) -> float | None:
    """Extract the strike price from a market question string."""
    m = _STRIKE_RE.search(question or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _detect_asset(question: str) -> tuple[str, str] | None:
    """Return (coingecko_id, binance_pair) if the question mentions a supported asset."""
    q = (question or "").lower()
    for prefix, (cg_id, bn_pair) in _ASSET_PAIRS.items():
        # Match short prefix (btc) or full name (bitcoin)
        if prefix in q or cg_id in q:
            return (cg_id, bn_pair)
    return None


def _seconds_until_resolution(end_date_str: str) -> float | None:
    """Parse an ISO end-date string and return seconds from now until resolution."""
    try:
        clean = end_date_str.replace("Z", "+00:00")
        end_dt = datetime.fromisoformat(clean)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return (end_dt - datetime.now(timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        return None


class ResolutionSniperStrategy(BaseStrategy):
    name = "resolution_sniper"
    description = (
        "Buy near-certain crypto 5-min binary outcomes 2+ min before resolution"
    )
    category = "crypto"
    default_params = {
        "min_price_distance_pct": 0.5,       # 0.5% above/below strike
        "min_seconds_to_resolution": 120,     # 2 minutes
        "max_seconds_to_resolution": 300,     # 5 minutes
        "min_market_price": 0.90,             # don't buy above 97c
        "max_market_price": 0.97,
        "min_volume": 500,
        "profit_target_pct": 0.05,
        "stop_loss_pct": 0.10,
        "max_hold_seconds": 240,
        "trailing_stop_activation_pct": 0.04,
        "max_open_positions": 3,
        "max_position_size": 50.0,
        "bankroll_pct": 0.08,
        "min_size_usd": 5.0,
        "min_confidence": 0.70,
        "fee_pct": 0.02,                      # 2% round-trip fee estimate
    }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Pass-through: resolution_sniper filters by crypto keywords in run_cycle."""
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}

        # --- auto-sell exits at cycle start ---
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell

            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params["profit_target_pct"]),
                stop_loss_pct=float(params["stop_loss_pct"]),
                max_hold_seconds=int(params["max_hold_seconds"]),
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Auto-sell start check failed: {e}")

        # --- fetch crypto prices from Binance (microstructure) ---
        price_cache: dict[str, float] = {}
        for prefix, (coingecko_id, _binance_pair) in _ASSET_PAIRS.items():
            try:
                micro = await compute_crypto_microstructure(coingecko_id)
                if micro and getattr(micro, "price", None):
                    price_cache[prefix] = float(micro.price)
            except Exception as e:
                logger.debug(f"[{self.name}] Failed to fetch {coingecko_id} price: {e}")

        if not price_cache:
            ctx.logger.warning(f"[{self.name}] No crypto prices available, skipping cycle")
            return result

        # --- fetch active crypto 5-min binary markets ---
        try:
            from backend.data.btc_markets import fetch_active_crypto_markets
            markets = []
            for asset_prefix in _ASSET_PAIRS:
                try:
                    asset_markets = await fetch_active_crypto_markets(asset=asset_prefix)
                    ctx.logger.info(f"[{self.name}] fetch_active_crypto_markets({asset_prefix}) returned {len(asset_markets)} markets")
                    for m in asset_markets:
                        markets.append({
                            "slug": m.slug,
                            "question": m.slug,
                            "endDate": m.window_end.isoformat() if m.window_end else None,
                            "outcomePrices": [str(m.up_price or 0), str(m.down_price or 0)],
                            "outcomes": ["Up", "Down"],
                            "volume": float(m.volume or 0),
                            "yes_price": float(m.up_price or 0),
                            "no_price": float(m.down_price or 0),
                        })
                except Exception as e:
                    ctx.logger.warning(f"[{self.name}] fetch_active_crypto_markets({asset_prefix}) failed: {e}")
            if not markets:
                ctx.logger.warning(f"[{self.name}] No crypto markets found from any asset — circuit breaker may be OPEN")
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] Gamma API fetch failed: {e}")
            result.errors.append(str(e))
            return result

        if not isinstance(markets, list):
            ctx.logger.warning(f"[{self.name}] Unexpected Gamma API response format")
            return result

        ctx.logger.info(f"[{self.name}] Fetched {len(markets)} markets from Gamma")

        # Debug: count filter stages
        _n_total = len(markets)
        _n_asset = 0
        _n_strike = 0
        _n_time = 0
        _n_dist = 0

        # --- query existing open positions for dedup ---
        existing_tickers: set[str] = set()
        open_count = 0
        try:
            from backend.models.database import Trade

            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            existing_tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            existing_tickers |= {t.event_slug for t in open_trades if t.event_slug}
            open_count = sum(1 for t in open_trades if t.strategy == self.name)
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] Could not query open trades: {e}")

        max_open = int(params["max_open_positions"])
        if open_count >= max_open:
            ctx.logger.info(
                f"[{self.name}] At max positions ({open_count}/{max_open}), skipping"
            )
            return result

        # --- scan markets for resolution snipes ---
        total_markets = len(markets)
        skip_no_asset = 0
        skip_no_strike = 0
        skip_time = 0
        skip_price_dist = 0
        skip_price_range = 0
        skip_volume = 0
        skip_existing = 0
        float(params["min_price_distance_pct"]) / 100.0
        min_sec = float(params["min_seconds_to_resolution"])
        max_sec = float(params["max_seconds_to_resolution"])
        min_mkt_price = float(params["min_market_price"])
        float(params["max_market_price"])
        min_volume = float(params["min_volume"])
        max_position_size = float(params["max_position_size"])
        bankroll_pct = float(params["bankroll_pct"])
        min_size_usd = float(params["min_size_usd"])
        min_confidence = float(params["min_confidence"])
        fee_pct = float(params["fee_pct"])

        # Get bankroll for sizing
        bankroll = float(getattr(ctx.settings, "INITIAL_BANKROLL", 1000.0))
        try:
            from backend.models.database import BotState, for_update

            state = for_update(ctx.db, ctx.db.query(BotState)).first()
            if state:
                if ctx.mode == "paper":
                    bankroll = float(state.paper_bankroll or bankroll)
                elif ctx.mode == "testnet":
                    bankroll = float(state.testnet_bankroll or bankroll)
                else:
                    bankroll = float(state.bankroll or bankroll)
        except Exception:
            pass

        slots_remaining = max_open - open_count

        for market in markets:
            if slots_remaining <= 0:
                break

            slug = market.get("slug") or market.get("conditionId") or ""
            if slug in existing_tickers:
                continue

            # Only crypto 5-min binaries (slug contains "updown")
            if "updown" not in slug.lower():
                continue

            # Volume filter
            volume = float(market.get("volume", 0) or 0)
            if volume < min_volume:
                skip_volume += 1
                continue

            # Already filtered to crypto markets in fetch — detect asset from slug
            slug = market.get("slug", "")
            question = market.get("question") or slug
            asset_ids = _detect_asset(slug + " " + question)
            if asset_ids is None:
                skip_no_asset += 1
                continue

            coingecko_id, _binance_pair = asset_ids
            asset_prefix = None
            for pfx, (cg_id, _) in _ASSET_PAIRS.items():
                if cg_id == coingecko_id:
                    asset_prefix = pfx
                    break
            if asset_prefix is None or asset_prefix not in price_cache:
                continue

            current_price = price_cache[asset_prefix]

            # Use market prices directly (from fetch_active_crypto_markets)
            yes_price = float(market.get("yes_price", 0) or 0)
            no_price = float(market.get("no_price", 0) or 0)
            if yes_price <= 0 or no_price <= 0:
                skip_no_strike += 1
                continue

            # Determine which side is near-certain (>0.90)
            # If yes_price > 0.90 → market thinks UP is likely → verify with spot price
            # If no_price > 0.90 → market thinks DOWN is likely → verify with spot price
            if yes_price >= min_mkt_price:
                buy_side = "yes"
                market_price = yes_price
            elif no_price >= min_mkt_price:
                buy_side = "no"
                market_price = no_price
            else:
                skip_price_range += 1
                continue

            # Time to resolution
            end_date_str = (
                market.get("endDate")
                or market.get("end_date_iso")
                or market.get("endDateIso")
            )
            if not end_date_str:
                continue

            secs_left = _seconds_until_resolution(end_date_str)
            if secs_left is None:
                continue
            if secs_left < min_sec or secs_left > max_sec:
                skip_time += 1
                continue

            # --- Edge model ---
            # Market already prices this outcome at 90-97c (near-certain).
            # We're buying because the market is slow to reprice near resolution.
            # Conservative true_prob: market_price + small buffer for time decay
            time_factor = max(0.0, 1.0 - (secs_left - min_sec) / (max_sec - min_sec))
            true_prob = min(0.99, market_price + 0.02 + time_factor * 0.02)

            edge = true_prob - market_price - fee_pct
            if edge < 0.005:
                skip_price_dist += 1
                continue

            confidence = true_prob
            if confidence < min_confidence:
                continue

            # clobTokenIds: get the token for our side
            clob_token_ids = market.get("clobTokenIds") or []
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except Exception:
                    clob_token_ids = []

            # YES is index 0, NO is index 1
            token_idx = 0 if buy_side == "yes" else 1
            if len(clob_token_ids) > token_idx:
                clob_token_id = str(clob_token_ids[token_idx])
            elif clob_token_ids:
                clob_token_id = str(clob_token_ids[0])
            else:
                continue

            # --- Position sizing ---
            kelly = edge / (1.0 - market_price) if market_price < 1.0 else 0.0
            size = min(
                max_position_size,
                bankroll * bankroll_pct,
                bankroll * kelly * 0.25,  # quarter-Kelly
            )
            size = max(size, min_size_usd)
            size = min(size, max_position_size)

            entry_price = market_price

            # Strike price not available from slug-based market data
            strike = 0.0
            dist_pct = 0.0

            decision = {
                "market_ticker": slug,
                "token_id": clob_token_id,
                "market_question": question,
                "direction": buy_side,
                "decision": "BUY",
                "entry_price": round(entry_price, 6),
                "size": round(size, 2),
                "suggested_size": round(size, 2),
                "edge": round(edge, 4),
                "confidence": round(confidence, 4),
                "model_probability": round(true_prob, 4),
                "market_probability": round(market_price, 4),
                "platform": settings.DEFAULT_VENUE,
                "strategy_name": self.name,
                "seconds_to_resolution": round(secs_left, 0),
                "price_distance_pct": round(dist_pct, 3),
                "current_asset_price": current_price,
                "strike_price": strike,
                "market_end_date": end_date_str,
                "volume": volume,
            }
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
                        f"ResolutionSnipe: {asset_prefix.upper()} "
                        f"${current_price:,.0f} vs strike ${strike:,.0f} "
                        f"({dist_pct:.2f}% away) | "
                        f"buy {buy_side.upper()} @ {market_price:.2%} | "
                        f"edge={edge:.2%} | {secs_left:.0f}s left"
                    ),
                )
                ctx.db.add(log_row)
            except Exception as e:
                ctx.logger.warning(f"[{self.name}] DecisionLog write failed: {e}")

            slots_remaining -= 1

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[{self.name}] DB commit failed: {e}")
            ctx.db.rollback()

        ctx.logger.info(
            f"[{self.name}] Cycle done: {result.decisions_recorded} snipe opportunities "
            f"(markets={total_markets}, skip: vol={skip_volume} asset={skip_no_asset} "
            f"strike={skip_no_strike} time={skip_time} dist={skip_price_dist} exist={skip_existing})"
        )

        # --- auto-sell exits at cycle end ---
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell

            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params["profit_target_pct"]),
                stop_loss_pct=float(params["stop_loss_pct"]),
                max_hold_seconds=int(params["max_hold_seconds"]),
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Auto-sell end check failed: {e}")

        return result
