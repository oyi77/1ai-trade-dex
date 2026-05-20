"""Market classifier -- categorize Polymarket markets into 25+ categories via keyword matching."""

from __future__ import annotations

import re

# Ordered list of (category, keywords).  First match wins, so more-specific
# categories (e.g. BTC_5m, BTC_ETF) must appear BEFORE their generic parent.
MARKET_CATEGORIES: dict[str, list[str]] = {
    "BTC_5m": ["bitcoin", "btc"],
    "BTC_ETF": ["bitcoin", "btc"],
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth"],
    "SOL": ["solana", "sol"],
    "Crypto_Alt": [
        "dogecoin",
        "doge",
        "shiba",
        "pepe",
        "xrp",
        "cardano",
        "ada",
        "polkadot",
        "dot",
        "avalanche",
        "avax",
        "matic",
        "polygon",
        "chainlink",
        "link",
        "uniswap",
        "uni",
        "defi",
        "crypto",
        "token",
        "altcoin",
        "meme coin",
    ],
    "Politics_US": [
        "president",
        "nominee",
        "trump",
        "biden",
        "election",
        "congress",
        "senate",
        "governor",
        "primary",
        "2024",
        "2025",
        "2026",
        "2028",
        "electoral",
        "swing state",
        "gop",
        "dnc",
        "republican",
        "democratic",
    ],
    "Politics_Global": [
        "prime minister",
        "election",
        "votes",
        "referendum",
        "parliament",
        "coalition",
        "presidential",
        "regime",
        "nato",
        "eu",
        "european union",
        "brexit",
        "france",
        "germany",
        "uk",
        "britain",
        "hungary",
        "poland",
        "turkey",
        "india",
        "japan",
        "brazil",
        "mexico",
        "canada",
        "australia",
    ],
    "Geopolitics": [
        "iran",
        "israel",
        "ukraine",
        "russia",
        "china",
        "war",
        "ceasefire",
        "sanction",
        "nato",
        "hormuz",
        "strait",
        "military",
        "invasion",
        "missile",
        "nuclear",
        "conflict",
        "taiwan",
        "gaza",
        "houthi",
        "hezbollah",
        "hamas",
    ],
    "Sports_Basketball": ["nba", "basketball", "ncaa"],
    "Sports_NFL": ["nfl", "football", "super bowl"],
    "Sports_Soccer": [
        "soccer",
        "premier league",
        "champions league",
        "la liga",
        "serie a",
        "bundesliga",
        "world cup",
    ],
    "Sports_Other": [
        "mlb",
        "nhl",
        "tennis",
        "cricket",
        "boxing",
        "ufc",
        "mma",
        "golf",
        "formula 1",
        "f1",
        "match",
        "championship",
        "playoff",
        "series",
        "race",
        "driver",
        "champion",
        "title",
        "round",
        "bout",
        "fight",
        "knockout",
    ],
    "Eurovision": ["eurovision", "song contest"],
    "Entertainment_Awards": [
        "oscar",
        "grammy",
        "emmy",
        "academy award",
        "mtv",
        "billboard",
        "golden globe",
        "tony",
    ],
    "Entertainment_Music": [
        "album",
        "song",
        "music",
        "concert",
        "tour",
        "spotify",
        "stream",
        "debut",
    ],
    "Entertainment_Film": [
        "movie",
        "film",
        "box office",
        "marvel",
        "dc",
        "disney",
        "netflix",
        "hbo",
        "streaming",
        "cinema",
    ],
    "Entertainment_Media": [
        "mrbeast",
        "elon musk",
        "celebrity",
        "influencer",
        "youtube",
        "tiktok",
        "twitch",
        "podcast",
    ],
    "Entertainment_Gaming": [
        "gta",
        "grand theft auto",
        "nintendo",
        "playstation",
        "xbox",
        "video game",
        "gaming",
        "esports",
        "steam",
        "nft",
        "metaverse",
    ],
    "Tech_Space": [
        "gemini",
        "spacex",
        "starship",
        "nasa",
        "space",
        "rocket",
        "launch",
        "satellite",
        "moon",
        "mars",
    ],
    "Tech_AI": [
        "ipo",
        "acquisition",
        "merger",
        "startup",
        "venture",
        "silicon valley",
        "google",
        "apple",
        "meta",
        "amazon",
        "microsoft",
        "nvidia",
        "tesla",
        "openai",
        "anthropic",
        "artificial intelligence",
        "robot",
        "automation",
        "chatgpt",
        "gpt",
        "llm",
        "model",
    ],
    "Regulation": [
        "bitcoin etf",
        "crypto regulation",
        "sec",
        "cftc",
        "cfpb",
        "fincen",
        "bill",
        "law",
        "court",
        "supreme court",
        "lawsuit",
        "regulation",
        "ban",
        "legal",
    ],
    "Finance": [
        "fed",
        "federal reserve",
        "interest rate",
        "rate cut",
        "rate hike",
        "inflation",
        "cpi",
        "gdp",
        "recession",
        "stock",
        "spx",
        "nasdaq",
        "dow",
        "s&p",
        "earnings",
        "microstrategy",
        "treasury",
        "yield",
        "bond",
    ],
    "Weather": [
        "temperature",
        "celsius",
        "fahrenheit",
        "weather",
        "hurricane",
        "tornado",
        "flood",
        "storm",
        "climate",
        "global warming",
        "heat",
        "snow",
        "rain",
    ],
    "Science_Health": [
        "covid",
        "vaccine",
        "pandemic",
        "virus",
        "drug",
        "fda",
        "medical",
        "health",
        "obesity",
        "longevity",
        "clinical",
        "trial",
        "cure",
        "treatment",
    ],
    "Science": [
        "nobel",
        "physics",
        "chemistry",
        "biology",
        "math",
        "discovery",
        "invention",
        "patent",
        "research",
    ],
}

# Short keywords that need word-boundary matching to avoid false positives.
# e.g. "eth" in "something", "sol" in "dissolve", "ai" in "said", "f1" in "f150"
_SHORT_KW = frozenset(
    {
        "eth",
        "sol",
        "ai",
        "sec",
        "fda",
        "gdp",
        "cpi",
        "fed",
        "dc",
        "eu",
        "uk",
        "f1",
        "nft",
        "ufc",
        "mma",
        "nhl",
        "nba",
        "nfl",
        "mlb",
        "uni",
        "dot",
        "ada",
        "xrp",
    }
)

# Pre-compiled word-boundary patterns for short keywords
_WB_CACHE: dict[str, re.Pattern] = {}


def _wb_pattern(word: str) -> re.Pattern:
    """Return a compiled word-boundary regex for *word*."""
    if word not in _WB_CACHE:
        _WB_CACHE[word] = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    return _WB_CACHE[word]


def _kw(text: str, *words: str) -> bool:
    """Return True if any word/phrase appears in text (case-insensitive).

    Short keywords (<=3 chars, or in _SHORT_KW) use word-boundary matching
    to avoid false positives (e.g. "eth" in "something").
    """
    lower = text.lower()
    for w in words:
        wl = w.lower().strip()
        if wl in _SHORT_KW or len(wl) <= 3:
            if _wb_pattern(wl).search(lower):
                return True
        else:
            if wl in lower:
                return True
    return False


def _build_rules() -> list[tuple[str, callable]]:
    """Build the ordered list of classification rules.

    Ordering is critical: more-specific rules must precede broader ones.
    """
    return [
        # --- BTC sub-categories (must precede generic BTC) ---
        (
            "BTC_5m",
            lambda t, s, tags: (
                _kw(t + " " + s + " " + tags, "bitcoin", "btc")
                and _kw(t + " " + s + " " + tags, "up or down", "5m", "1m", "15m")
            ),
        ),
        (
            "BTC_ETF",
            lambda t, s, tags: (
                _kw(t + " " + s + " " + tags, "bitcoin", "btc")
                and _kw(t + " " + s + " " + tags, "etf")
            ),
        ),
        # --- Crypto ---
        ("BTC", lambda t, s, tags: _kw(t + " " + s + " " + tags, "bitcoin", "btc")),
        ("ETH", lambda t, s, tags: _kw(t + " " + s + " " + tags, "ethereum", "eth")),
        ("SOL", lambda t, s, tags: _kw(t + " " + s + " " + tags, "solana", "sol")),
        # --- Regulation (before Crypto_Alt so "sec crypto regulation" -> Regulation) ---
        (
            "Regulation",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "bitcoin etf",
                "crypto regulation",
                "sec",
                "cftc",
                "cfpb",
                "fincen",
                "bill",
                "law",
                "court",
                "supreme court",
                "lawsuit",
                "regulation",
                "ban",
                "legal",
            ),
        ),
        (
            "Crypto_Alt",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "dogecoin",
                "doge",
                "shiba",
                "pepe",
                "xrp",
                "cardano",
                "ada",
                "polkadot",
                "dot",
                "avalanche",
                "avax",
                "matic",
                "polygon",
                "chainlink",
                "link",
                "uniswap",
                "uni",
                "defi",
                "crypto",
                "token",
                "altcoin",
                "meme coin",
            ),
        ),
        # --- Sports (specific before general) ---
        (
            "Sports_Basketball",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags, "nba", "basketball", "ncaa"
            ),
        ),
        (
            "Sports_NFL",
            lambda t, s, tags: _kw(t + " " + s + " " + tags, "nfl", "super bowl"),
        ),
        (
            "Sports_Soccer",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "soccer",
                "premier league",
                "champions league",
                "la liga",
                "serie a",
                "bundesliga",
                "world cup",
            ),
        ),
        (
            "Sports_Other",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "mlb",
                "nhl",
                "tennis",
                "cricket",
                "boxing",
                "ufc",
                "mma",
                "golf",
                "formula 1",
                "f1",
                "match",
                "game",
                "championship",
                "playoff",
                "series",
                "race",
                "driver",
                "champion",
                "title",
                "round",
                "bout",
                "fight",
                "knockout",
            ),
        ),
        # --- Entertainment (specific before general) ---
        (
            "Eurovision",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags, "eurovision", "song contest"
            ),
        ),
        (
            "Entertainment_Awards",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "oscar",
                "grammy",
                "emmy",
                "academy award",
                "mtv",
                "billboard",
                "golden globe",
                "tony",
            ),
        ),
        (
            "Entertainment_Gaming",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "gta",
                "grand theft auto",
                "nintendo",
                "playstation",
                "xbox",
                "video game",
                "gaming",
                "esports",
                "steam",
                "nft",
                "metaverse",
            ),
        ),
        (
            "Entertainment_Music",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "album",
                "song",
                "music",
                "concert",
                "tour",
                "spotify",
                "stream",
                "debut",
            ),
        ),
        (
            "Entertainment_Film",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "movie",
                "film",
                "box office",
                "marvel",
                "dc",
                "disney",
                "netflix",
                "hbo",
                "streaming",
                "cinema",
            ),
        ),
        (
            "Entertainment_Media",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "mrbeast",
                "elon musk",
                "celebrity",
                "influencer",
                "youtube",
                "tiktok",
                "twitch",
                "podcast",
            ),
        ),
        # --- Geopolitics ---
        (
            "Geopolitics",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "iran",
                "israel",
                "ukraine",
                "russia",
                "china",
                "war",
                "ceasefire",
                "sanction",
                "nato",
                "hormuz",
                "strait",
                "military",
                "invasion",
                "missile",
                "nuclear",
                "conflict",
                "taiwan",
                "gaza",
                "houthi",
                "hezbollah",
                "hamas",
            ),
        ),
        # --- Politics (Global before US -- "prime minister" etc. are unambiguous) ---
        (
            "Politics_Global",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "prime minister",
                "parliament",
                "referendum",
                "votes",
                "coalition",
                "presidential",
                "regime",
                "eu",
                "european union",
                "brexit",
                "france",
                "germany",
                "uk",
                "britain",
                "hungary",
                "poland",
                "turkey",
                "india",
                "japan",
                "brazil",
                "mexico",
                "canada",
                "australia",
            ),
        ),
        (
            "Politics_US",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "president",
                "nominee",
                "trump",
                "biden",
                "election",
                "congress",
                "senate",
                "governor",
                "primary",
                "2024",
                "2025",
                "2026",
                "2028",
                "electoral",
                "swing state",
                "gop",
                "dnc",
                "republican",
                "democratic",
            ),
        ),
        # --- Tech ---
        (
            "Tech_Space",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "gemini",
                "spacex",
                "starship",
                "nasa",
                "space",
                "rocket",
                "launch",
                "satellite",
                "moon",
                "mars",
            ),
        ),
        (
            "Tech_AI",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "ipo",
                "acquisition",
                "merger",
                "startup",
                "venture",
                "silicon valley",
                "google",
                "apple",
                "meta",
                "amazon",
                "microsoft",
                "nvidia",
                "tesla",
                "openai",
                "anthropic",
                "artificial intelligence",
                "robot",
                "automation",
                "chatgpt",
                "gpt",
                "llm",
                "model",
            ),
        ),
        # --- Finance ---
        (
            "Finance",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "fed",
                "federal reserve",
                "interest rate",
                "rate cut",
                "rate hike",
                "inflation",
                "cpi",
                "gdp",
                "recession",
                "stock",
                "spx",
                "nasdaq",
                "dow",
                "s&p",
                "earnings",
                "microstrategy",
                "treasury",
                "yield",
                "bond",
            ),
        ),
        # --- Weather ---
        (
            "Weather",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "temperature",
                "celsius",
                "fahrenheit",
                "weather",
                "hurricane",
                "tornado",
                "flood",
                "storm",
                "climate",
                "global warming",
                "heat",
                "snow",
                "rain",
            ),
        ),
        # --- Science ---
        (
            "Science_Health",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "covid",
                "vaccine",
                "pandemic",
                "virus",
                "drug",
                "fda",
                "medical",
                "health",
                "obesity",
                "longevity",
                "clinical",
                "trial",
                "cure",
                "treatment",
            ),
        ),
        (
            "Science",
            lambda t, s, tags: _kw(
                t + " " + s + " " + tags,
                "nobel",
                "physics",
                "chemistry",
                "biology",
                "math",
                "discovery",
                "invention",
                "patent",
                "research",
            ),
        ),
    ]


# Lazy-initialised rule list
_rules: list[tuple[str, callable]] | None = None


def _get_rules() -> list[tuple[str, callable]]:
    global _rules
    if _rules is None:
        _rules = _build_rules()
    return _rules


def classify_market(
    title: str,
    slug: str = "",
    event_slug: str = "",
    tags: list[str] | None = None,
) -> str:
    """Classify a Polymarket market into one of 25+ categories.

    Parameters
    ----------
    title : str
        Market title / question.
    slug : str
        URL slug for the market.
    event_slug : str
        Parent event slug.
    tags : list[str] | None
        Optional tag list attached to the market.

    Returns
    -------
    str
        Category name, or "Other" if nothing matched.
    """
    if not title and not slug and not event_slug and not tags:
        return "Other"

    tag_str = " ".join(tags) if tags else ""

    for category, rule in _get_rules():
        if rule(title, slug, tag_str):
            return category

    return "Other"
