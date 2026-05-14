"""
RED phase TDD tests for TokenBucketRateLimiter — must FAIL until T12 is implemented.
"""
import time

import pytest

from backend.core.errors import RateLimitError

# Import will fail until T12 implemented:
from backend.core.external_rate_limiter import TokenBucketRateLimiter

def test_same_market_two_orders_within_10s():
    limiter = TokenBucketRateLimiter(per_market_limit=1, per_market_window=10, global_limit=3, global_window=1)
    limiter.acquire("BTC-UP")
    with pytest.raises(RateLimitError):
        limiter.acquire("BTC-UP")

def test_global_limit_four_orders_in_one_second():
    limiter = TokenBucketRateLimiter(per_market_limit=1, per_market_window=10, global_limit=3, global_window=1)
    limiter.acquire("AAPL-UP")
    limiter.acquire("TSLA-UP")
    limiter.acquire("BTC-UP")
    with pytest.raises(RateLimitError):
        limiter.acquire("ETH-UP")

def test_one_order_per_market_spaced_10s_apart():
    limiter = TokenBucketRateLimiter(per_market_limit=1, per_market_window=10, global_limit=3, global_window=1)
    limiter.acquire("BTC-UP")
    time.sleep(10.1)
    limiter.acquire("BTC-UP")

def test_sliding_window_cleanup_resets_limit():
    limiter = TokenBucketRateLimiter(per_market_limit=1, per_market_window=5, global_limit=3, global_window=1)
    limiter.acquire("BTC-UP")
    time.sleep(5.1)
    limiter.acquire("BTC-UP")
