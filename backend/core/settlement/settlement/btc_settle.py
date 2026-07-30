"""BTC 5-minute UP/DOWN market settlement logic."""

import re as _re
from datetime import datetime, timedelta, timezone

from backend.models.database import Trade
from backend.core.settlement.settlement_helpers import (
    calculate_pnl,
    total_loss_settlement_value,
)
from backend.monitoring.hft_metrics import record_execution
from loguru import logger


async def _settle_btc_5min_trade(trade: Trade, now: datetime) -> Trade | None:
    """Settle a BTC 5-min UP/DOWN market trade whose window has expired.

    Resolution strategy (in order of reliability):
    1. Polymarket API via fetch_btc_market_for_settlement (if market is closed)
    2. CEX BTC price at window end (Binance/Coinbase 1m klines) — determine if BTC
       went UP or DOWN relative to window start
    3. If both fail, mark as expired_unresolved instead of push (zero PnL misreports wins)
    """
    # BUG FIX: Skip trades already settled (e.g. by closed_unresolved in a prior
    # cycle). Without this guard, a trade settled as loss could be re-settled as
    # win/loss via CEX fallback, creating duplicate settlements and corrupting PnL.
    if trade.settled:
        return None

    ticker = trade.market_ticker or ""
    match = _re.search(r"btc-updown-5m-(\d+)", ticker)
    if not match:
        return None

    window_start_ts = int(match.group(1))
    window_end = datetime.fromtimestamp(window_start_ts + 300, tz=timezone.utc)

    if now < window_end:
        return None

    entry_price = float(trade.entry_price or 0)
    size = float(trade.size or 0)
    direction = (trade.direction or "up").lower()

    try:
        from backend.data.btc_markets import fetch_btc_market_for_settlement

        btc_market = await fetch_btc_market_for_settlement(ticker)
        if btc_market and btc_market.closed:
            if direction == "up":
                won = btc_market.up_price > 0.9
            elif direction == "down":
                won = btc_market.down_price > 0.9
            else:
                won = False

            # For Polymarket binary markets: up=YES, down=NO
            # settlement_value=1.0 means YES won, 0.0 means NO won
            # direction=up wins when settlement_value=1.0 (YES)
            # direction=down wins when settlement_value=0.0 (NO)
            if won:
                trade.result = "win"
                # down wins → NO won → settlement_value=0.0
                # up wins → YES won → settlement_value=1.0
                sv = 0.0 if direction == "down" else 1.0
                trade.pnl = calculate_pnl(trade, sv)
                trade.settlement_value = sv
                record_execution(
                    strategy=trade.strategy or "btc_5min",
                    side=trade.direction or "up",
                    status="settled_win",
                    latency_s=0.0,
                )
            else:
                trade.result = "loss"
                # down loses → YES won → settlement_value=1.0
                # up loses → NO won → settlement_value=0.0
                sv = 1.0 if direction == "down" else 0.0
                trade.pnl = calculate_pnl(trade, sv)
                trade.settlement_value = sv
                record_execution(
                    strategy=trade.strategy or "btc_5min",
                    side=trade.direction or "down",
                    status="settled_loss",
                    latency_s=0.0,
                )

            trade.settled = True
            trade.settlement_time = now
            trade.settlement_source = "btc_5min_auto"
            return trade
    except Exception as e:
        logger.debug(f"btc_5min Polymarket settlement fetch failed for {ticker}: {e}")

    delayed_settle_seconds = 120
    if now < window_end + timedelta(seconds=delayed_settle_seconds):
        logger.info(
            f"BTC 5min {ticker}: window ended {delayed_settle_seconds}s ago, "
            "allowing more time for Polymarket resolution"
        )
        return None

    try:
        from backend.data.crypto import fetch_binance_klines

        klines = await fetch_binance_klines(limit=60)
        if klines and len(klines) > 1:
            start_price = None
            end_price = None
            for k in klines:
                k_ts_ms = int(float(k[0])) if isinstance(k[0], (int, float, str)) else 0
                k_ts_s = k_ts_ms // 1000
                if k_ts_s == window_start_ts:
                    start_price = float(k[4])
                if k_ts_s == window_start_ts + 300:
                    end_price = float(k[4])

            if start_price is not None and end_price is not None:
                went_up = end_price > start_price
                won = (direction == "up" and went_up) or (
                    direction == "down" and not went_up
                )

                if won:
                    trade.result = "win"
                    sv = 0.0 if direction == "down" else 1.0
                    trade.pnl = calculate_pnl(trade, sv)
                    trade.settlement_value = sv
                else:
                    trade.result = "loss"
                    sv = 1.0 if direction == "down" else 0.0
                    trade.pnl = calculate_pnl(trade, sv)
                    trade.settlement_value = sv

                trade.settled = True
                trade.settlement_time = now
                trade.settlement_source = "btc_5min_cex_fallback"
                logger.info(
                    f"BTC 5min {ticker}: settled via CEX fallback start=${start_price:.2f} "
                    f"end=${end_price:.2f} dir={direction} won={won} pnl=${trade.pnl:+.2f}"
                )
                return trade
            elif end_price is not None or start_price is not None:
                _reference_price = end_price or start_price
                for k in klines:
                    k_ts_ms = (
                        int(float(k[0])) if isinstance(k[0], (int, float, str)) else 0
                    )
                    k_ts_s = k_ts_ms // 1000
                    if window_start_ts <= k_ts_s <= window_start_ts + 300:
                        if start_price is None:
                            start_price = float(k[4])
                        end_price = float(k[4])
                if start_price is not None and end_price is not None:
                    went_up = end_price > start_price
                    won = (direction == "up" and went_up) or (
                        direction == "down" and not went_up
                    )
                    if won:
                        trade.result = "win"
                        sv = 0.0 if direction == "down" else 1.0
                        trade.pnl = calculate_pnl(trade, sv)
                        trade.settlement_value = sv
                    else:
                        trade.result = "loss"
                        sv = 1.0 if direction == "down" else 0.0
                        trade.pnl = calculate_pnl(trade, sv)
                        trade.settlement_value = sv
                    trade.settled = True
                    trade.settlement_time = now
                    trade.settlement_source = "btc_5min_cex_fallback_scan"
                    logger.info(
                        f"BTC 5min {ticker}: settled via CEX scan start=${start_price:.2f} "
                        f"end=${end_price:.2f} dir={direction} won={won} pnl=${trade.pnl:+.2f}"
                    )
                    return trade
    except Exception as e:
        logger.warning(f"BTC 5min CEX fallback also failed for {ticker}: {e}")

    max_settle_age_hours = 24
    trade_ts = trade.timestamp
    if trade_ts and trade_ts.tzinfo is None:
        trade_ts = trade_ts.replace(tzinfo=timezone.utc)
    if trade_ts and now < trade_ts + timedelta(hours=max_settle_age_hours):
        logger.info(f"BTC 5min {ticker}: could not resolve yet, will retry next cycle")
        return None

    trade.settled = True
    trade.result = "loss"
    loss_sv = total_loss_settlement_value(trade.direction)
    trade.pnl = calculate_pnl(trade, loss_sv)
    trade.settlement_time = now
    trade.settlement_source = "btc_5min_unresolved"
    trade.settlement_value = loss_sv
    record_execution(
        strategy=trade.strategy or "btc_5min",
        side=trade.direction or "n/a",
        status="settled_expired",
        latency_s=0.0,
    )
    logger.warning(
        f"BTC 5min {ticker}: could not resolve via Polymarket or CEX after {max_settle_age_hours}h, "
        f"marking as expired_unresolved (assumed loss)"
    )
    return trade
