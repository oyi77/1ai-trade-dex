"""
Polymarket, Kalshi, and Binance resolution functions.

Extracted from settlement_helpers.py.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, Tuple

import httpx
from cachetools import TTLCache

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.models.database import Trade

from loguru import logger

# Module-level: track consecutive 404s per market_id (bounded TTLCache: 1000 entries, 1 hour TTL)
_market_404_counts: TTLCache = TTLCache(maxsize=1000, ttl=3600)

# Module-level: cache already-resolved markets to skip redundant gamma REST calls
# TTL=3600s (1h) — resolved markets don't change; prevents 429 on repeated settlement cycles
_resolved_market_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)

# Semaphore: cap concurrent gamma API calls to avoid 429 rate limiting
# Initialized lazily in _resolve_markets (asyncio event loop must be running)
_gamma_semaphore: Optional[asyncio.Semaphore] = None

# In-flight deduplication: maps ticker -> asyncio.Event
# Prevents thundering-herd cache stampede when multiple coroutines resolve
# the same conditionId concurrently before any result is cached.
_gamma_inflight: dict = {}


def _looks_like_token_id(value: str) -> bool:
    """Detect Polymarket CLOB token IDs.

    Token IDs are long decimal strings (typically 70+ digits, ERC1155 token IDs
    derived from conditionId + outcome index). They're distinct from:
      - Numeric Gamma market IDs (short, < 12 digits)
      - Slugs (contain hyphens / non-digit chars)
      - Condition IDs (start with 0x)
    """
    if not value or not isinstance(value, str):
        return False
    if not value.isdigit():
        return False
    return len(value) >= 20


async def _resolve_pm_by_token_id(token_id: str) -> Tuple[bool, Optional[float]]:
    """Resolve a Polymarket market via CLOB token_id (Gamma API).

    Uses ``gamma-api.polymarket.com/markets?clob_token_ids={tid}&closed=true``
    which is the only reliable path when we only have a token_id (no slug, no
    numeric market id).

    Picks the outcome index by matching the token_id's position inside the
    market's ``clobTokenIds`` array, then reads the corresponding
    ``outcomePrices[i]``. settlement_value is the price of OUR token's outcome
    (1.0 = our outcome won, 0.0 = our outcome lost). The caller's calculate_pnl
    treats settlement_value=1.0 as YES/UP-wins.

    Note: this returns the value from the *token's* perspective normalized to
    yes/up semantics — i.e. if the trade's token is the "Yes" leg and Yes wins,
    we return 1.0; if the token is the "No" leg and No wins, we still return
    1.0 because *our* outcome won. This matches how stuck trades are stored:
    direction='up' simply means "the token we bought".
    """
    try:
        client = get_shared_client()
        for closed_flag in ("true", "false"):
            try:
                resp = await client.get(
                    f"{settings.GAMMA_API_URL}/markets",
                    params={
                        "clob_token_ids": token_id,
                        "closed": closed_flag,
                        "limit": 1,
                    },
                    timeout=10.0,
                )
            except (httpx.TimeoutException, httpx.ConnectTimeout):
                continue

            if resp.status_code != 200:
                continue

            data = resp.json()
            if not data or not isinstance(data, list):
                continue

            market = data[0]
            clob_token_ids = market.get("clobTokenIds", [])
            outcome_prices = market.get("outcomePrices", [])

            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (ValueError, TypeError):
                    clob_token_ids = []
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except (ValueError, TypeError):
                    # Handle non-JSON strings like '[0.5, 0.5]'
                    try:
                        cleaned = outcome_prices.strip("[] ")
                        outcome_prices = [
                            float(x.strip())
                            for x in cleaned.split(",")
                            if x.strip()
                        ]
                    except (ValueError, TypeError):
                        outcome_prices = []

            if not clob_token_ids or not outcome_prices:
                continue
            if len(clob_token_ids) != len(outcome_prices):
                continue

            idx = None
            for i, tid in enumerate(clob_token_ids):
                if str(tid) == str(token_id):
                    idx = i
                    break
            if idx is None:
                continue

            is_closed = bool(market.get("closed", False))
            uma_status = (market.get("umaResolutionStatus") or "").lower()
            resolved = is_closed or uma_status == "resolved"
            if not resolved:
                continue

            try:
                our_price = float(outcome_prices[idx])
            except (ValueError, TypeError):
                continue

            if our_price >= 0.99:
                logger.info(
                    f"PM token-id {token_id[:16]}... resolved: WON "
                    f"(idx={idx}, price={our_price})"
                )
                return True, 1.0
            if our_price <= 0.01:
                logger.info(
                    f"PM token-id {token_id[:16]}... resolved: LOST "
                    f"(idx={idx}, price={our_price})"
                )
                return True, 0.0

            return False, None

        return False, None

    except Exception as e:
        logger.warning(
            f"[resolution._resolve_pm_by_token_id] {type(e).__name__}: "
            f"Failed for token {token_id[:16]}...: {e}"
        )
        return False, None


async def fetch_polymarket_resolution(
    market_id: str, event_slug: Optional[str] = None, condition_id: Optional[str] = None
) -> Tuple[bool, Optional[float]]:
    """
    Fetch actual market resolution from Polymarket API.

    For BTC 5-min markets, uses event slug to find the market.
    When condition_id is provided, queries Gamma by condition_id directly.

    Returns: (is_resolved, settlement_value)
        - settlement_value: 1.0 if our outcome (Up/Yes leg) won, 0.0 if it lost.

    For wallet-reconciliation imports the market_ticker is often a CLOB
    token_id (long decimal string). In that case we route through
    ``_resolve_pm_by_token_id`` which handles outcome-index mapping correctly.
    """
    # New: try condition_id first (most reliable for settlement)
    if condition_id:
        try:
            client = get_shared_client()
            resp = await client.get(
                f"{settings.GAMMA_API_URL}/markets",
                params={"condition_id": condition_id},
            )
            if resp.status_code == 200:
                markets = resp.json()
                if isinstance(markets, list) and markets:
                    result = _parse_market_resolution(markets[0])
                    if result[0]:
                        return result
        except Exception:
            logger.exception(
                f"[resolution] Gamma API resolution failed for market {market_id}"
            )

    if _looks_like_token_id(market_id):
        resolved, value = await _resolve_pm_by_token_id(market_id)
        if resolved:
            return resolved, value

    try:
        client = get_shared_client()
        # Try event slug first (more reliable for BTC 5-min markets)
        if event_slug:
            response = await client.get(
                f"{settings.GAMMA_API_URL}/events",
                params={"slug": event_slug},
            )
            response.raise_for_status()
            events = response.json()

            if events:
                event = events[0] if isinstance(events, list) else events
                markets = event.get("markets", [])
                if markets:
                    return _parse_market_resolution(markets[0])

        # Try slug-based query first (market_id may be a slug, not numeric ID)
        try:
            slug_response = await client.get(
                f"{settings.GAMMA_API_URL}/markets",
                params={"slug": market_id},
                timeout=15.0,
            )
            if slug_response.status_code == 200:
                slug_results = slug_response.json()
                if isinstance(slug_results, list) and slug_results:
                    result = _parse_market_resolution(slug_results[0])
                    # If Gamma says unresolved but prices are 0/null, check CLOB
                    if not result[0] and _has_invalid_prices(slug_results[0]):
                        clob_result = await _check_clob_resolution(market_id)
                        if clob_result[0]:
                            return clob_result
                    return result
        except (httpx.TimeoutException, httpx.ConnectTimeout):
            logger.debug(
                f"Market query timeout for {market_id}, trying event query"
            )

        # If market query times out, try querying by event slug
        # Extract event slug by removing the last suffix (e.g., -scf, -cel4, -draw)
        if "-" in market_id:
            parts = market_id.rsplit("-", 1)
            if len(parts) == 2 and len(parts[1]) <= 5:
                event_slug = parts[0]
                try:
                    event_response = await client.get(
                        f"{settings.GAMMA_API_URL}/events",
                        params={"slug": event_slug},
                        timeout=15.0,
                    )
                    if event_response.status_code == 200:
                        events = event_response.json()
                        if events and isinstance(events, list):
                            event = events[0]
                            markets = event.get("markets", [])
                            for market in markets:
                                if market.get("slug") == market_id:
                                    return _parse_market_resolution(market)
                except Exception as e:
                    logger.debug(
                        f"[resolution.fetch_polymarket_resolution] {type(e).__name__}: Event query failed for {event_slug}: {e}",
                        exc_info=True,
                    )

        # Fallback: try market ID directly (works for numeric IDs)
        url = f"{settings.GAMMA_API_URL}/markets/{market_id}"
        response = await client.get(url)

        if response.status_code in (404, 422):
            _market_404_counts[market_id] = _market_404_counts.get(market_id, 0) + 1
            if _market_404_counts[market_id] >= 3:
                logger.debug(
                    f"Skipping market {market_id} — 3+ consecutive 404/422s"
                )
                # Try CLOB as last resort before giving up
                clob_result = await _check_clob_resolution(market_id)
                if clob_result[0]:
                    return clob_result
                return False, None
            return await _search_market_in_events(market_id)

        response.raise_for_status()
        market = response.json()
        return _parse_market_resolution(market)

    except Exception as e:
        logger.warning(
            f"[resolution.fetch_polymarket_resolution] {type(e).__name__}: Failed to fetch resolution for {event_slug or market_id}: {e}"
        )
        return False, None


def _has_invalid_prices(market: dict) -> bool:
    """Check if market has invalid/zero prices that suggest delisted market."""
    outcome_prices = market.get("outcomePrices", [])
    if not outcome_prices:
        return True
    try:
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except (ValueError, TypeError):
                cleaned = outcome_prices.strip("[] ")
                outcome_prices = [
                    float(x.strip()) for x in cleaned.split(",") if x.strip()
                ]
        prices = [float(p) for p in outcome_prices if p]
        if not prices or all(p == 0 for p in prices):
            return True
    except (ValueError, TypeError):
        return True
    return False


async def _check_clob_resolution(market_id: str) -> Tuple[bool, Optional[float]]:
    """Check CLOB API for market closed status."""
    try:
        client = get_shared_client()
        response = await client.get(
            f"{settings.CLOB_API_URL}/markets?slug={market_id}"
        )
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, dict) and "data" in data:
                markets = data["data"]
                if markets and isinstance(markets, list):
                    market = markets[0]
                    if market.get("closed"):
                        logger.info(f"CLOB confirms market {market_id} is closed")
                        return True, None
    except Exception as e:
        logger.debug(
            f"[resolution._check_clob_resolution] {type(e).__name__}: CLOB resolution check failed for {market_id}: {e}",
            exc_info=True,
        )
    return False, None


async def _search_market_in_events(market_id: str) -> Tuple[bool, Optional[float]]:
    """Search for market in events (both active and closed)."""
    try:
        client = get_shared_client()
        for closed in [True, False]:
            params = {"closed": str(closed).lower(), "limit": 200}
            response = await client.get(
                f"{settings.GAMMA_API_URL}/events", params=params
            )
            response.raise_for_status()
            events = response.json()

            for event in events:
                for market in event.get("markets", []):
                    if str(market.get("id")) == str(market_id):
                        return _parse_market_resolution(market)

        return False, None

    except Exception as e:
        logger.warning(
            f"[resolution._search_market_in_events] {type(e).__name__}: Failed to search for market {market_id}: {e}"
        )
        return False, None


def _parse_market_resolution(market: dict) -> Tuple[bool, Optional[float]]:
    """
    Parse market data to determine if resolved and outcome.

    Handles both Yes/No and Up/Down outcomes.
    - outcomePrices[0] > 0.99 -> first outcome won (Yes or Up)
    - outcomePrices[0] < 0.01 -> second outcome won (No or Down)

    Also supports early resolution heuristic: if the market is not yet
    officially closed but prices are extreme AND the event appears to have
    concluded, treat it as resolved so we don't wait hours for Polymarket
    to flip the closed flag.
    """
    is_closed = market.get("closed", False)

    outcome_prices = market.get("outcomePrices", [])
    if not outcome_prices:
        return False, None

    try:
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except (ValueError, TypeError):
                cleaned = outcome_prices.strip("[] ")
                outcome_prices = [
                    float(x.strip()) for x in cleaned.split(",") if x.strip()
                ]

        first_price = float(outcome_prices[0]) if outcome_prices else 0.5

        # --- Officially closed: use tight thresholds (existing logic) ---
        if is_closed:
            if first_price > 0.99:
                logger.info(f"Market {market.get('id')} resolved: UP/YES won")
                return True, 1.0
            elif first_price < 0.01:
                logger.info(f"Market {market.get('id')} resolved: DOWN/NO won")
                return True, 0.0
            else:
                return False, None

        # --- Early resolution heuristic (market not yet closed) ---
        # Graduated thresholds based on how strong the resolution signal is:
        #
        # Tier 1: events[0].ended == True → 0.90/0.10 (confirmed ended)
        # Tier 2: endDate passed + 30min → 0.90/0.10 (likely ended, not flagged)
        # Tier 3: endDate passed + 2h   → 0.80/0.20 (definitely over, slow resolution)
        # Tier 4: endDate passed + 6h   → 0.70/0.30 (stale market, force resolve)
        #
        # The key insight: if endDate has passed, the event is OVER — prices
        # reflect the known outcome, not speculation. Polymarket is just slow
        # to officially close/resolve.

        events = market.get("events", [])
        has_ended_flag = False
        is_live = False
        if events and isinstance(events, list):
            ev = events[0] if isinstance(events[0], dict) else {}
            has_ended_flag = ev.get("ended") is True
            is_live = ev.get("live") is True and not has_ended_flag

        # Compute hours_past_end BEFORE the is_live check so we can
        # override the live flag for games that are clearly over.
        now = datetime.now(timezone.utc)
        end_date_str = market.get("endDate")
        hours_past_end = 0.0
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                if now > end_date:
                    hours_past_end = (now - end_date).total_seconds() / 3600.0
            except (ValueError, TypeError):
                logger.exception(
                    "[resolution] failed to parse market end_date for early resolution check"
                )

        # If the game is explicitly live AND the endDate hasn't been
        # surpassed by a wide margin, don't early-resolve.
        # Polymarket's `live` flag often stays True for HOURS after a
        # game ends, so we only trust it when endDate hasn't passed by
        # much (< 30 minutes).
        if is_live and hours_past_end < 0.5:
            return False, None

        # Gamma API endDate can reference a group/series date, not the
        # actual market resolution.  Only block the ZOMBIE tier (48h+)
        # when the market is still actively trading — because the loose
        # 0.55/0.45 thresholds can misfire on misleading endDates.
        # Tiers 2-4 are fine because they require strong price signals
        # (≥0.65 or ≤0.35) that only occur on genuinely finished markets.
        market_still_open = (
            market.get("active", False)
            and not market.get("closed", False)
            and not has_ended_flag
        )

        # Select threshold based on strongest signal
        # Graduated tiers: more time past endDate = looser thresholds.
        # Rationale: once endDate passes, the price IS the outcome —
        # Polymarket is just slow to officially close. We can resolve
        # earlier to free up capital.
        if has_ended_flag:
            # Tier 1: API confirms event ended
            early_threshold_high = 0.90
            early_threshold_low = 0.10
            tier = "ended-flag"
        elif hours_past_end >= 48.0:
            # Tier 6: 48+ hours past endDate — extremely stale.
            logger.info(
                f"Market {market.get('id')} Tier6 check: market_still_open={market_still_open}, "
                f"hours_past_end={hours_past_end:.0f}, first_price={first_price:.4f}"
            )
            if market_still_open:
                # Market is still flagged active — Gamma API endDate may be
                # misleading (group/series date).  But if the price is
                # extremely decisive (≥0.95/≤0.05), the outcome is clear
                # regardless of the active flag.  Otherwise, skip.
                if first_price >= 0.95 or first_price <= 0.05:
                    early_threshold_high = 0.95
                    early_threshold_low = 0.05
                    tier = f"zombie-forced-{hours_past_end:.0f}h"
                else:
                    logger.info(
                        f"Market {market.get('id')} skipping zombie resolution: "
                        f"still active, endDate {hours_past_end:.0f}h ago (likely misleading)"
                    )
                    return False, None
            else:
                # Market not actively open but still not officially closed
                early_threshold_high = 0.70
                early_threshold_low = 0.30
                tier = f"zombie-{hours_past_end:.0f}h"
        elif hours_past_end >= 12.0:
            if market_still_open:
                # Still-open markets 12h+ past endDate: resolve only if
                # price is extremely decisive — Polymarket often leaves
                # the active flag on for hours after resolution.
                if first_price >= 0.95 or first_price <= 0.05:
                    early_threshold_high = 0.95
                    early_threshold_low = 0.05
                    tier = f"very-stale-forced-{hours_past_end:.1f}h"
                else:
                    return False, None
            else:
                early_threshold_high = 0.70
                early_threshold_low = 0.30
                tier = f"very-stale-{hours_past_end:.1f}h"
        elif hours_past_end >= 6.0:
            if market_still_open:
                # 6h+ past endDate and still "active": only force-resolve
                # on very strong signals (≥0.95/≤0.05).
                if first_price >= 0.95 or first_price <= 0.05:
                    early_threshold_high = 0.95
                    early_threshold_low = 0.05
                    tier = f"stale-forced-{hours_past_end:.1f}h"
                else:
                    return False, None
            else:
                early_threshold_high = 0.75
                early_threshold_low = 0.25
                tier = f"stale-{hours_past_end:.1f}h"
        elif hours_past_end >= 2.0:
            if market_still_open:
                # 2-6h past endDate: only resolve on extreme prices
                if first_price >= 0.97 or first_price <= 0.03:
                    early_threshold_high = 0.97
                    early_threshold_low = 0.03
                    tier = f"overdue-forced-{hours_past_end:.1f}h"
                else:
                    return False, None
            else:
                early_threshold_high = 0.70
                early_threshold_low = 0.30
                tier = f"overdue-{hours_past_end:.1f}h"
        elif hours_past_end >= 0.5:
            # Tier 2: 30min-2h past endDate
            early_threshold_high = 0.85
            early_threshold_low = 0.15
            tier = f"recent-{hours_past_end:.1f}h"
        else:
            # Event hasn't ended yet — use very strict thresholds
            early_threshold_high = 0.97
            early_threshold_low = 0.03
            tier = "pre-end"

        if first_price > early_threshold_high:
            # Only require event_concluded check for pre-end tier
            if tier == "pre-end":
                event_concluded = _check_event_concluded(market)
                if not event_concluded:
                    return False, None
            logger.info(
                f"Market {market.get('id')} early-resolved (price={first_price:.3f}, "
                f"tier={tier}, threshold={early_threshold_high}): UP/YES won"
            )
            return True, 1.0
        elif first_price < early_threshold_low:
            if tier == "pre-end":
                event_concluded = _check_event_concluded(market)
                if not event_concluded:
                    return False, None
            logger.info(
                f"Market {market.get('id')} early-resolved (price={first_price:.3f}, "
                f"tier={tier}, threshold={early_threshold_low}): DOWN/NO won"
            )
            return True, 0.0

        return False, None

    except (ValueError, IndexError, TypeError) as e:
        logger.warning(f"Failed to parse outcome prices: {e}")
        return False, None


def _check_event_concluded(market: dict) -> bool:
    """
    Determine whether the underlying event has concluded, even if Polymarket
    hasn't set closed=True yet.

    For sports markets: checks ``events[0].ended`` flag.
    For non-sports:     checks whether ``endDate`` has passed by ≥2 hours.
    """
    now = datetime.now(timezone.utc)

    events = market.get("events", [])
    if events and isinstance(events, list):
        event = events[0] if isinstance(events[0], dict) else {}
        if event.get("ended") is True:
            return True

    end_date_str = market.get("endDate")
    if end_date_str:
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            hours_past = (
                (now - end_date).total_seconds() / 3600.0 if now > end_date else 0.0
            )
            if hours_past >= 2.0:
                return True
            # Only trust is_live flag when endDate hasn't been exceeded
            if events and isinstance(events, list):
                ev = events[0] if isinstance(events[0], dict) else {}
                if (
                    ev.get("live") is True
                    and ev.get("ended") is not True
                    and hours_past < 0.5
                ):
                    return False
        except (ValueError, TypeError):
            logger.exception(
                "[resolution] failed to parse market end_date for BTC updown resolution"
            )

    return False


async def _resolve_btc_updown_via_binance(ticker: str) -> Optional[float]:
    """
    Resolve BTC up/down 5-min market via Binance price data.
    Slug format: btc-updown-5m-TIMESTAMP
    Returns 1.0 if BTC went up, 0.0 if down. None if unable to determine.
    """
    parts = ticker.split("-")
    if len(parts) < 4:
        return None
    try:
        market_ts = int(parts[-1])
    except ValueError:
        return None

    start_ms = market_ts * 1000
    end_ms = (market_ts + 300) * 1000
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=5"

    client = get_shared_client()
    resp = await client.get(url, timeout=10.0)
    data = resp.json()
    if not data:
        return None
    open_price = float(data[0][1])
    close_price = float(data[-1][4])
    result = 1.0 if close_price > open_price else 0.0
    logger.info(
        f"[resolution] BTC Binance fallback: {ticker} open=${open_price:.2f} close=${close_price:.2f} -> {'up' if result == 1.0 else 'down'}"
    )
    return result


async def _fetch_kalshi_resolution(ticker: str) -> Tuple[bool, Optional[float]]:
    """Fetch resolution status for a Kalshi market."""
    try:
        from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present

        if not kalshi_credentials_present():
            return False, None

        client = KalshiClient()
        data = await client.get_market(ticker)
        market = data.get("market", data)

        status = market.get("status", "")
        result = market.get("result", "")

        if status in ("finalized", "determined") and result:
            if result == "yes":
                return True, 1.0
            elif result == "no":
                return True, 0.0

        return False, None

    except Exception as e:
        logger.warning(
            f"[resolution._fetch_kalshi_resolution] {type(e).__name__}: Failed to fetch Kalshi resolution for {ticker}: {e}"
        )
        return False, None


async def fetch_resolution_for_trade(trade: Trade) -> Tuple[bool, Optional[float]]:
    """Platform-aware resolution dispatch via market registry.

    Returns: (is_resolved, settlement_value) where settlement_value ∈ {0.0, 1.0}.
    Routes to Kalshi or Polymarket based on trade.platform; defaults to polymarket
    when platform is missing (legacy rows).

    Tries market provider registry first, falls back to legacy platform-specific
    resolution functions when registry is unavailable.
    """
    platform = (getattr(trade, "platform", None) or "polymarket").lower()

    # Try registered provider first
    try:
        from backend.markets.provider_registry import market_registry

        provider = market_registry.get(platform)
        if provider and hasattr(provider, "resolve_market"):
            is_resolved, value = await provider.resolve_market(trade.market_ticker)
            if is_resolved:
                return True, value
    except Exception:
        logger.exception(
            f"[resolution] provider.resolve_market failed for {trade.market_ticker}"
        )

    # Legacy fallback — wrap in error handling to prevent scheduler hang on API timeout
    try:
        if platform == "kalshi":
            return await _fetch_kalshi_resolution(trade.market_ticker)
        return await fetch_polymarket_resolution(
            trade.market_ticker,
            event_slug=getattr(trade, "event_slug", None),
            condition_id=getattr(trade, "condition_id", None),
        )
    except Exception:
        logger.exception(
            f"[resolution] Resolution fetch failed for {trade.market_ticker} (platform={platform})"
        )

    # BTC up/down 5-min fallback: resolve via Binance price data
    ticker = getattr(trade, "market_ticker", "") or ""
    if ticker.startswith("btc-updown-5m-"):
        try:
            result = await _resolve_btc_updown_via_binance(ticker)
            if result is not None:
                return True, result
        except Exception:
            logger.exception(f"[resolution] BTC Binance fallback failed for {ticker}")

    # Return unresolved status — trade will be marked as expired_unresolved to avoid PnL misreports
    return False, None
