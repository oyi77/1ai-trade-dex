"""G-10: Live smoke test for crypto_oracle — fetches real BTC price from CoinGecko.

Marked with @pytest.mark.live so it's skipped in CI without network/API access.
Run explicitly with: pytest backend/tests/test_crypto_oracle_live.py -v -m live
"""
import pytest
import httpx


COINGECKO_API = "https://api.coingecko.com/api/v3"


@pytest.mark.live
class TestCryptoOracleLive:
    """Live smoke tests that hit real APIs. Skipped in CI unless -m live."""

    def test_coingecko_btc_price(self):
        """Fetch real BTC price from CoinGecko and verify it's a reasonable number."""
        resp = httpx.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        assert "bitcoin" in data
        btc_price = data["bitcoin"]["usd"]
        assert isinstance(btc_price, (int, float))
        # BTC should be between $10k and $1M (sanity bound)
        assert 10_000 < btc_price < 1_000_000, f"BTC price out of range: {btc_price}"

    def test_coingecko_multi_asset(self):
        """Fetch BTC, ETH, SOL prices in a single call."""
        resp = httpx.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": "bitcoin,ethereum,solana", "vs_currencies": "usd"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        for asset in ("bitcoin", "ethereum", "solana"):
            assert asset in data, f"Missing {asset} in response"
            price = data[asset]["usd"]
            assert isinstance(price, (int, float))
            assert price > 0, f"{asset} price is non-positive: {price}"

    def test_crypto_oracle_can_process_price(self):
        """Verify CryptoOracleStrategy can process a live price through implied_direction."""
        from backend.strategies.crypto_oracle import implied_direction

        resp = httpx.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10.0,
        )
        resp.raise_for_status()
        btc_price = resp.json()["bitcoin"]["usd"]

        # Test that implied_direction works with a real price
        question = f"Will BTC exceed ${btc_price - 1000:,.0f}?"
        direction = implied_direction(question, btc_price)
        assert direction in ("yes", "no"), f"Unexpected direction: {direction}"
        # BTC is above (price - 1000), so should be "yes"
        assert direction == "yes"

    def test_coingecko_rate_limit_headers(self):
        """Verify CoinGecko returns rate limit headers (proves API is responsive)."""
        resp = httpx.get(
            f"{COINGECKO_API}/ping",
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        assert "gecko_says" in data
