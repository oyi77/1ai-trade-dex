"""News Frontrun Strategy — trade crypto 5-min binaries on breaking news.

Edge: when market-moving crypto news breaks (ETF approval, hack, regulation),
Polymarket 5-min binaries are slow to reprice.  Buy the directional side
before the crowd catches up.

Sources: RSS feeds from major crypto outlets (no API key needed).
Classification: keyword-based (fast, no LLM latency).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field

from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext
from backend.data.shared_client import get_shared_client
from backend.data.btc_markets import fetch_active_crypto_markets
from backend.config import settings

from loguru import logger

# ── News sources (free RSS, no auth) ──────────────────────────────────────
RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://www.theblock.co/rss.xml",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/feed",
]

# ── Market-moving keywords ────────────────────────────────────────────────
# Each keyword has (pattern, direction, weight)
# direction: "bullish" or "bearish"
# weight: 0.0-1.0 (how market-moving)

BULLISH_KEYWORDS = [
    (r"\betf\s*(approved|pass|launch)", "bullish", 0.95),
    (r"\bpartnership\b", "bullish", 0.4),
    (r"\bupgrade\b", "bullish", 0.3),
    (r"\badoption\b", "bullish", 0.3),
    (r"\bwhale\s*(buy|accumul)", "bullish", 0.5),
    (r"\binstitutional\b.*\bbuy", "bullish", 0.6),
    (r"\btreasury\b.*\bbuy", "bullish", 0.5),
    (r"\brecord\s*high", "bullish", 0.7),
    (r"\bbull\s*run", "bullish", 0.3),
    (r"\brally\b", "bullish", 0.3),
    (r"\bpump\b", "bullish", 0.3),
    (r"\bsurges?\b", "bullish", 0.4),
    (r"\bsoar", "bullish", 0.4),
    (r"\bspike", "bullish", 0.3),
    (r"\bbreakout\b", "bullish", 0.4),
    (r"\bnew\s*all[\s-]*time\s*high", "bullish", 0.9),
    (r"\bnation.*\badopt", "bullish", 0.8),
    (r"\breserve\b.*\bcrypto", "bullish", 0.8),
    (r"\bstrategic\b.*\breserve", "bullish", 0.9),
]

BEARISH_KEYWORDS = [
    (r"\bhack(ed|ing)?\b", "bearish", 0.9),
    (r"\bexploit\b", "bearish", 0.8),
    (r"\bregulat.*\bcrack", "bearish", 0.7),
    (r"\bban(ned)?\b", "bearish", 0.8),
    (r"\bwhale\s*(sell|dump)", "bearish", 0.5),
    (r"\bcrash\b", "bearish", 0.6),
    (r"\bplunge", "bearish", 0.5),
    (r"\bdump\b", "bearish", 0.4),
    (r"\bsell[\s-]*off", "bearish", 0.4),
    (r"\bfud\b", "bearish", 0.2),
    (r"\bscam\b", "bearish", 0.5),
    (r"\barrest\b.*\bceo", "bearish", 0.8),
    (r"\bbankrupt", "bearish", 0.9),
    (r"\binsolvent", "bearish", 0.9),
    (r"\bponzi\b", "bearish", 0.9),
    (r"\bsecurities?\b.*\bcharge", "bearish", 0.7),
    (r"\bsec\s*sues?\b", "bearish", 0.8),
    (r"\bdelisting\b", "bearish", 0.7),
]

# Asset keyword mapping
ASSET_KEYWORDS = {
    "btc": [
        r"\bbtc\b", r"\bbitcoin\b", r"\bsatoshi\b",
        r"\bbtc\s*etf\b", r"\bblackrock\b",
    ],
    "eth": [
        r"\beth\b", r"\bethereum\b", r"\bether\b",
        r"\beth\s*etf\b", r"\bvitalik\b",
    ],
    "sol": [
        r"\bsol\b", r"\bsolana\b", r"\bphantom\b",
    ],
}

# ── Seen article cache (avoid re-processing) ──────────────────────────────
_seen_hashes: set[str] = set()
_seen_expiry: dict[str, float] = {}
_SEEN_TTL = 3600  # 1 hour


def _hash_article(title: str, link: str) -> str:
    return hashlib.md5(f"{title}:{link}".encode()).hexdigest()


def _is_seen(h: str) -> bool:
    now = time.time()
    # Expire old entries
    expired = [k for k, v in _seen_expiry.items() if now - v > _SEEN_TTL]
    for k in expired:
        _seen_hashes.discard(k)
        _seen_expiry.pop(k)
    return h in _seen_hashes


def _mark_seen(h: str) -> None:
    _seen_hashes.add(h)
    _seen_expiry[h] = time.time()


@dataclass
class NewsSignal:
    title: str
    link: str
    source: str
    direction: str  # "bullish" or "bearish"
    strength: float  # 0.0-1.0
    asset: str  # "btc", "eth", "sol"
    timestamp: float = field(default_factory=time.time)


def _classify_news(title: str) -> tuple[str, float] | None:
    """Classify news as bullish/bearish with strength. Returns (direction, weight) or None."""
    t = title.lower()
    best: tuple[str, float] | None = None

    for pattern, direction, weight in BULLISH_KEYWORDS + BEARISH_KEYWORDS:
        if re.search(pattern, t):
            if best is None or weight > best[1]:
                best = (direction, weight)

    return best


def _detect_asset(title: str) -> str | None:
    """Detect which crypto asset the news is about."""
    t = title.lower()
    for asset, patterns in ASSET_KEYWORDS.items():
        for p in patterns:
            if re.search(p, t):
                return asset
    return None


async def _fetch_rss_feed(client, url: str) -> list[dict]:
    """Fetch and parse RSS feed. Returns list of {title, link}."""
    try:
        r = await client.get(url, timeout=8.0, follow_redirects=True)
        if r.status_code != 200:
            return []

        text = r.text
        items = []

        # Simple XML parsing (no lxml dependency)
        # Match <item> or <entry> blocks
        for match in re.finditer(
            r"<(?:item|entry)[^>]*>(.*?)</(?:item|entry)>",
            text,
            re.DOTALL | re.IGNORECASE,
        ):
            block = match.group(1)
            title_m = re.search(r"<title[^>]*>(.*?)</title>", block, re.DOTALL | re.IGNORECASE)
            link_m = re.search(r"<link[^>]*>(.*?)</link>", block, re.DOTALL | re.IGNORECASE)
            if not link_m:
                link_m = re.search(r'<link[^>]*href="([^"]*)"', block, re.IGNORECASE)

            if title_m:
                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()
                link = link_m.group(1).strip() if link_m else ""
                if title:
                    items.append({"title": title, "link": link})

        return items[:20]  # max 20 per feed

    except Exception as e:
        logger.debug(f"[news_frontrun] RSS fetch failed {url}: {e}")
        return []


class NewsFrontrunStrategy(BaseStrategy):
    """Trade crypto 5-min binaries on breaking market-moving news."""

    name = "news_frontrun"
    description = (
        "Frontrun market-moving crypto news on Polymarket 5-min binaries. "
        "Monitors RSS feeds from major crypto outlets, classifies direction, "
        "and trades before the crowd reprices."
    )
    category = "news"

    default_params = {
        "min_strength": 0.5,  # minimum news strength to trade
        "max_position_usd": 5.0,
        "kelly_fraction": 0.20,
        "max_open_positions": 2,
        "max_per_asset": 1,
        "cooldown_seconds": 300,  # don't re-trade same asset within 5min
        "profit_target_pct": 0.05,
        "stop_loss_pct": 0.04,
        "max_hold_seconds": 240,
        "min_seconds_to_resolution": 60,  # at least 1 min left
        "max_minutes_to_resolution": 25,  # news effects last longer than momentum
    }

    # Track last trade time per asset to avoid overtrading
    _last_trade: dict[str, float] = {}

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}

        min_strength = float(params.get("min_strength", 0.5))
        max_position = float(params.get("max_position_usd", 5.0))
        cooldown = float(params.get("cooldown_seconds", 300))
        max_open = int(params.get("max_open_positions", 2))
        int(params.get("max_per_asset", 1))

        # Check open positions
        from backend.models.database import Trade

        open_count = (
            ctx.db.query(Trade)
            .filter(
                Trade.strategy == self.name,
                Trade.settled.is_(False),
                Trade.trading_mode == ctx.mode,
            )
            .count()
        )
        if open_count >= max_open:
            logger.debug(f"[news_frontrun] {open_count} open >= max {max_open}, skip")
            return result

        # Auto-sell check (always run, even if no signals)
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell

            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params.get("profit_target_pct", 0.12)),
                stop_loss_pct=float(params.get("stop_loss_pct", 0.08)),
                max_hold_seconds=int(params.get("max_hold_seconds", 240)),
            )
        except Exception as e:
            logger.warning(f"[news_frontrun] auto-sell check failed: {e}")

        # Fetch all RSS feeds in parallel
        http = get_shared_client()
        feed_tasks = [_fetch_rss_feed(http, url) for url in RSS_FEEDS]
        feed_results = await asyncio.gather(*feed_tasks, return_exceptions=True)

        all_items: list[dict] = []
        for r in feed_results:
            if isinstance(r, list):
                all_items.extend(r)

        if not all_items:
            logger.debug("[news_frontrun] No items from any RSS feed")
            return result

        # Classify and filter news
        signals: list[NewsSignal] = []
        for item in all_items:
            title = item.get("title", "")
            link = item.get("link", "")

            # Skip already-seen articles
            h = _hash_article(title, link)
            if _is_seen(h):
                continue

            # Classify
            classification = _classify_news(title)
            if classification is None:
                continue

            direction, strength = classification
            if strength < min_strength:
                continue

            # Detect asset
            asset = _detect_asset(title)
            if asset is None:
                continue  # can't trade if we don't know which asset

            # Cooldown check
            now = time.time()
            last = self._last_trade.get(asset, 0)
            if now - last < cooldown:
                logger.debug(f"[news_frontrun] {asset} cooldown ({now-last:.0f}s < {cooldown}s)")
                continue

            _mark_seen(h)
            signals.append(NewsSignal(
                title=title,
                link=link,
                source=item.get("source", "rss"),
                direction=direction,
                strength=strength,
                asset=asset,
            ))

            logger.info(
                f"[news_frontrun] SIGNAL: {direction.upper()} {asset.upper()} "
                f"strength={strength:.2f} | {title[:80]}"
            )

        if not signals:
            return result

        # Trade the strongest signal
        signals.sort(key=lambda s: s.strength, reverse=True)
        signal = signals[0]

        # Find matching 5-min markets
        try:
            markets = await fetch_active_crypto_markets(asset=signal.asset)
        except Exception as e:
            logger.warning(f"[news_frontrun] market fetch failed: {e}")
            return result

        if not markets:
            logger.debug(f"[news_frontrun] no markets for {signal.asset}")
            return result

        # Filter to markets with enough time
        min_secs = float(params.get("min_seconds_to_resolution", 120))
        max_mins = float(params.get("max_minutes_to_resolution", 8))
        valid_markets = [
            m for m in markets
            if min_secs <= m.time_until_end <= max_mins * 60
        ]

        if not valid_markets:
            logger.debug(f"[news_frontrun] no valid markets (need {min_secs}-{max_mins*60}s)")
            return result

        # Pick the market with most time remaining (best for news to play out)
        market = max(valid_markets, key=lambda m: m.time_until_end)

        # Determine token and entry price
        if signal.direction == "bullish":
            token_id = market.up_token_id
            entry_price = market.up_price
            direction = "up"
        else:
            token_id = market.down_token_id
            entry_price = market.down_price
            direction = "down"

        if not token_id or entry_price <= 0:
            logger.debug(f"[news_frontrun] no valid token/price for {market.slug}")
            return result

        # Size by strength
        max_pos = min(max_position, ctx.bankroll * 0.15)
        max_pos = max(max_pos, float(getattr(settings, "MIN_ORDER_USDC", 1.0)))
        size = round(max_pos * signal.strength, 2)

        # Record decision
        decision = {
            "decision": "BUY",
            "market_ticker": market.slug,
            "token_id": token_id,
            "direction": direction,
            "entry_price": round(entry_price, 6),
            "size": size,
            "suggested_size": size,
            "edge": round(signal.strength * 0.15, 4),  # estimated edge from news
            "confidence": round(signal.strength, 4),
            "model_probability": round(0.5 + signal.strength * 0.3, 4),
            "market_probability": round(entry_price, 4),
            "platform": settings.DEFAULT_VENUE,
            "strategy_name": self.name,
            "reasoning": (
                f"NEWS {signal.direction.upper()}: {signal.title[:60]} | "
                f"asset={signal.asset} strength={signal.strength:.2f}"
            ),
            "news_title": signal.title[:120],
            "news_strength": signal.strength,
            "news_direction": signal.direction,
            "market_end_date": market.window_end.isoformat() if market.window_end else "",
        }

        result.decisions.append(decision)
        result.decisions_recorded += 1
        result.trades_attempted += 1

        # Update cooldown
        self._last_trade[signal.asset] = time.time()

        # Record decision log
        try:
            from backend.core.decisions import record_decision_standalone

            record_decision_standalone(
                self.name,
                market.slug,
                "BUY",
                confidence=signal.strength,
                signal_data=decision,
                reason=(
                    f"NEWS {signal.direction.upper()} {signal.asset.upper()} "
                    f"strength={signal.strength:.2f} | {signal.title[:50]}"
                ),
            )
        except Exception as e:
            logger.warning(f"[news_frontrun] decision log failed: {e}")

        # Auto-sell check
        try:
            from backend.core.auto_sell import check_strategy_positions_for_auto_sell

            await check_strategy_positions_for_auto_sell(
                self.name,
                clob_client=ctx.clob,
                profit_target_pct=float(params.get("profit_target_pct", 0.12)),
                stop_loss_pct=float(params.get("stop_loss_pct", 0.08)),
                max_hold_seconds=int(params.get("max_hold_seconds", 240)),
            )
        except Exception as e:
            logger.warning(f"[news_frontrun] auto-sell check failed: {e}")

        return result
