"""Tests for backend.core.market_classifier."""


from backend.core.market_classifier import MARKET_CATEGORIES, classify_market


class TestClassifyMarket:
    """Keyword-based market classification tests."""

    # --- Crypto ---------------------------------------------------------

    def test_btc_5m(self):
        assert classify_market("Bitcoin Up or Down - 5m window") == "BTC_5m"

    def test_btc_general(self):
        assert classify_market("Will Bitcoin reach $100k?") == "BTC"

    def test_btc_etf(self):
        assert classify_market("Bitcoin ETF approval") == "BTC_ETF"

    def test_eth(self):
        assert classify_market("Ethereum merge success") == "ETH"

    def test_sol(self):
        assert classify_market("Solana price above $200") == "SOL"

    def test_crypto_alt(self):
        assert classify_market("Dogecoin to the moon") == "Crypto_Alt"

    # --- Politics -------------------------------------------------------

    def test_politics_us_trump(self):
        assert classify_market("Trump wins 2028 election") == "Politics_US"

    def test_politics_us_biden(self):
        assert classify_market("Biden nominee confirmed") == "Politics_US"

    def test_politics_global(self):
        assert classify_market("UK prime minister election") == "Politics_Global"

    # --- Geopolitics ----------------------------------------------------

    def test_geopolitics(self):
        assert classify_market("Iran Israel ceasefire") == "Geopolitics"

    # --- Sports ---------------------------------------------------------

    def test_sports_basketball(self):
        assert classify_market("NBA finals winner") == "Sports_Basketball"

    def test_sports_nfl(self):
        assert classify_market("Super Bowl champion") == "Sports_NFL"

    def test_sports_soccer(self):
        assert classify_market("Champions League final") == "Sports_Soccer"

    def test_sports_other_ufc(self):
        assert classify_market("UFC 300 main event") == "Sports_Other"

    # --- Entertainment --------------------------------------------------

    def test_eurovision(self):
        assert classify_market("Eurovision 2025 winner") == "Eurovision"

    def test_entertainment_awards(self):
        assert classify_market("Oscar best picture") == "Entertainment_Awards"

    def test_entertainment_music(self):
        assert classify_market("Taylor Swift new album") == "Entertainment_Music"

    def test_entertainment_film(self):
        assert classify_market("Marvel box office opening") == "Entertainment_Film"

    def test_entertainment_media(self):
        assert classify_market("MrBeast subscriber count") == "Entertainment_Media"

    def test_entertainment_gaming(self):
        assert classify_market("GTA 6 release date") == "Entertainment_Gaming"

    # --- Tech -----------------------------------------------------------

    def test_tech_space(self):
        assert classify_market("SpaceX Starship launch") == "Tech_Space"

    def test_tech_ai(self):
        assert classify_market("OpenAI GPT-5 release") == "Tech_AI"

    # --- Regulation / Finance / Weather / Science -----------------------

    def test_regulation(self):
        assert classify_market("SEC crypto regulation") == "Regulation"

    def test_finance(self):
        assert classify_market("Fed rate cut June") == "Finance"

    def test_weather(self):
        assert classify_market("Hurricane category 5 Florida") == "Weather"

    def test_science_health(self):
        assert classify_market("FDA vaccine approval") == "Science_Health"

    # --- Fallback -------------------------------------------------------

    def test_other_fallback(self):
        assert classify_market("Something random unclassified") == "Other"

    def test_empty_string(self):
        assert classify_market("") == "Other"

    # --- Tags parameter -------------------------------------------------

    def test_tags_parameter(self):
        assert classify_market("x", tags=["bitcoin"]) == "BTC"

    def test_tags_crypto_alt(self):
        assert classify_market("Will it happen?", tags=["dogecoin"]) == "Crypto_Alt"

    def test_slug_used(self):
        assert classify_market("", slug="solana-price-above-200") == "SOL"


class TestMarketCategories:
    """MARKET_CATEGORIES dict tests."""

    def test_dict_is_not_empty(self):
        assert len(MARKET_CATEGORIES) > 0

    def test_has_expected_keys(self):
        # Just check a few critical keys exist
        for key in ("BTC", "ETH", "SOL", "Finance", "Weather"):
            assert key in MARKET_CATEGORIES

    def test_values_are_lists(self):
        for cat, keywords in MARKET_CATEGORIES.items():
            assert isinstance(keywords, list), f"{cat} keywords should be a list"
            assert len(keywords) > 0, f"{cat} should have at least one keyword"
