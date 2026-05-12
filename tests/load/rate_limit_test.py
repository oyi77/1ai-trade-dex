#!/usr/bin/env python3
"""
Rate Limit Test Suite - Task 31

Tests rate limiting on all protected endpoints:
- /api/trades (100/minute limit)
- /api/signals (50/minute limit)
- /api/strategies (20/minute limit)

Verifies:
1. Requests at limit succeed (200/401)
2. Requests over limit return 429
3. Rate limit headers are correct
4. Reset works after timeout
5. Multi-IP gets independent limits
"""

import asyncio
import time
import httpx
import logging
from typing import Dict, Tuple
from dataclasses import dataclass
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate-limited endpoints."""
    endpoint: str
    limit: int
    description: str


# Rate limit configurations
ENDPOINTS = [
    RateLimitConfig("/api/trades", 100, "Trades endpoint"),
    RateLimitConfig("/api/signals", 50, "Signals endpoint"),
    RateLimitConfig("/api/strategies", 20, "Strategies endpoint"),
]

BASE_URL = "http://localhost:8000"
TIMEOUT = 30.0


class RateLimitTester:
    """Test rate limiting behavior."""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.results: Dict[str, Dict] = {}

    async def test_endpoint_at_limit(self, config: RateLimitConfig) -> Tuple[int, int, Dict]:
        """
        Test endpoint at its rate limit.
        
        Returns:
            (successful_count, rate_limited_count, headers_from_last_request)
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"Testing {config.endpoint} - Limit: {config.limit}/minute")
        logger.info(f"{'='*70}")

        successful = 0
        rate_limited = 0
        last_headers = {}
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Send requests up to and beyond the limit
            for i in range(config.limit + 5):
                try:
                    response = await client.get(
                        f"{self.base_url}{config.endpoint}",
                        headers={"X-Forwarded-For": "127.0.0.1"}
                    )
                    
                    last_headers = dict(response.headers)
                    
                    if response.status_code == 429:
                        rate_limited += 1
                        if i < config.limit + 2:  # Log first few 429s
                            logger.info(
                                f"  Request {i+1}: 429 Too Many Requests "
                                f"(Remaining: {response.headers.get('X-RateLimit-Remaining', 'N/A')})"
                            )
                    elif response.status_code in [200, 401]:
                        successful += 1
                        if i % 10 == 0 or i == config.limit - 1:
                            logger.info(
                                f"  Request {i+1}: {response.status_code} OK "
                                f"(Remaining: {response.headers.get('X-RateLimit-Remaining', 'N/A')})"
                            )
                    else:
                        logger.warning(f"  Request {i+1}: Unexpected status {response.status_code}")
                        
                except httpx.TimeoutException:
                    logger.error(f"  Request {i+1}: Timeout")
                except Exception as e:
                    logger.error(f"  Request {i+1}: Error - {e}")

        return successful, rate_limited, last_headers

    def verify_rate_limit_headers(self, headers: Dict, config: RateLimitConfig) -> bool:
        """Verify rate limit headers are present and correct."""
        logger.info(f"\nVerifying rate limit headers for {config.endpoint}:")
        
        required_headers = [
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ]
        
        all_present = True
        for header in required_headers:
            if header in headers:
                logger.info(f"  ✓ {header}: {headers[header]}")
            else:
                logger.error(f"  ✗ {header}: MISSING")
                all_present = False
        
        # Verify header values
        try:
            limit = int(headers.get("X-RateLimit-Limit", 0))
            remaining = int(headers.get("X-RateLimit-Remaining", -1))
            reset = int(headers.get("X-RateLimit-Reset", 0))
            
            if limit == config.limit:
                logger.info(f"  ✓ Limit value correct: {limit}")
            else:
                logger.error(f"  ✗ Limit value incorrect: {limit} (expected {config.limit})")
                all_present = False
            
            if remaining >= 0:
                logger.info(f"  ✓ Remaining value valid: {remaining}")
            else:
                logger.error(f"  ✗ Remaining value invalid: {remaining}")
                all_present = False
            
            if reset > time.time():
                logger.info(f"  ✓ Reset timestamp valid: {reset} ({reset - time.time():.1f}s from now)")
            else:
                logger.error(f"  ✗ Reset timestamp invalid: {reset}")
                all_present = False
                
        except (ValueError, TypeError) as e:
            logger.error(f"  ✗ Error parsing header values: {e}")
            all_present = False
        
        return all_present

    async def test_reset_after_timeout(self, config: RateLimitConfig, wait_seconds: int = 65) -> bool:
        """
        Test that rate limit resets after timeout.
        
        Note: This test waits for the full timeout period.
        """
        logger.info(f"\nTesting rate limit reset for {config.endpoint}:")
        logger.info(f"  Waiting {wait_seconds} seconds for rate limit window to reset...")
        
        # Wait for reset window
        for i in range(wait_seconds):
            if i % 10 == 0:
                logger.info(f"    {i}/{wait_seconds}s elapsed...")
            await asyncio.sleep(1)
        
        # Try a request after reset
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(
                    f"{self.base_url}{config.endpoint}",
                    headers={"X-Forwarded-For": "127.0.0.1"}
                )
                
                if response.status_code in [200, 401]:
                    logger.info(f"  ✓ Request succeeded after reset: {response.status_code}")
                    remaining = response.headers.get("X-RateLimit-Remaining", "N/A")
                    logger.info(f"    Remaining: {remaining}")
                    return True
                else:
                    logger.error(f"  ✗ Request failed after reset: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"  ✗ Error testing reset: {e}")
            return False

    async def test_multi_ip_independent_limits(self) -> bool:
        """
        Test that different IPs get independent rate limits.
        """
        logger.info(f"\n{'='*70}")
        logger.info("Testing Multi-IP Independent Limits")
        logger.info(f"{'='*70}")
        
        config = ENDPOINTS[0]  # Use /api/trades for this test
        ips = ["192.168.1.1", "192.168.1.2", "192.168.1.3"]
        results = {}
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for ip in ips:
                logger.info(f"\nTesting IP: {ip}")
                successful = 0
                rate_limited = 0
                
                # Send requests from this IP
                for i in range(config.limit + 3):
                    try:
                        response = await client.get(
                            f"{self.base_url}{config.endpoint}",
                            headers={"X-Forwarded-For": ip}
                        )
                        
                        if response.status_code == 429:
                            rate_limited += 1
                        elif response.status_code in [200, 401]:
                            successful += 1
                            
                    except Exception as e:
                        logger.error(f"  Error: {e}")
                
                results[ip] = {
                    "successful": successful,
                    "rate_limited": rate_limited,
                    "expected_limit": config.limit
                }
                
                logger.info(
                    f"  IP {ip}: {successful} successful, {rate_limited} rate limited "
                    f"(expected ~{config.limit} successful)"
                )
        
        # Verify each IP got independent limits
        all_correct = True
        for ip, result in results.items():
            if result["successful"] >= result["expected_limit"] - 2:  # Allow small variance
                logger.info(f"  ✓ IP {ip} got independent limit")
            else:
                logger.error(f"  ✗ IP {ip} did not get independent limit")
                all_correct = False
        
        return all_correct

    async def test_retry_after_header(self, config: RateLimitConfig) -> bool:
        """Test that Retry-After header is present on 429 responses."""
        logger.info(f"\nTesting Retry-After header for {config.endpoint}:")
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Exhaust the limit
            for i in range(config.limit + 1):
                response = await client.get(
                    f"{self.base_url}{config.endpoint}",
                    headers={"X-Forwarded-For": "127.0.0.1"}
                )
                
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        logger.info(f"  ✓ Retry-After header present: {retry_after}s")
                        try:
                            retry_seconds = int(retry_after)
                            if 0 < retry_seconds <= 60:
                                logger.info(f"  ✓ Retry-After value valid: {retry_seconds}s")
                                return True
                            else:
                                logger.error(f"  ✗ Retry-After value out of range: {retry_seconds}s")
                                return False
                        except ValueError:
                            logger.error(f"  ✗ Retry-After value not an integer: {retry_after}")
                            return False
                    else:
                        logger.error("  ✗ Retry-After header missing on 429 response")
                        return False
        
        logger.error("  ✗ Never received 429 response")
        return False

    async def run_all_tests(self, skip_reset_test: bool = True) -> Dict:
        """Run all rate limit tests."""
        logger.info("\n" + "="*70)
        logger.info("RATE LIMIT TEST SUITE")
        logger.info("="*70)
        logger.info(f"Base URL: {self.base_url}")
        logger.info(f"Start time: {datetime.now().isoformat()}")
        
        summary = {
            "endpoints": {},
            "multi_ip": None,
            "all_passed": True
        }
        
        # Test each endpoint
        for config in ENDPOINTS:
            endpoint_results = {
                "config": config,
                "at_limit": None,
                "headers_valid": None,
                "retry_after": None,
                "reset_works": None,
            }
            
            # Test at limit
            successful, rate_limited, headers = await self.test_endpoint_at_limit(config)
            
            at_limit_passed = (
                successful >= config.limit - 2 and  # Allow small variance
                rate_limited >= 1
            )
            endpoint_results["at_limit"] = {
                "passed": at_limit_passed,
                "successful": successful,
                "rate_limited": rate_limited,
                "expected_limit": config.limit
            }
            
            if not at_limit_passed:
                summary["all_passed"] = False
                logger.error(
                    f"✗ {config.endpoint}: Expected ~{config.limit} successful, "
                    f"got {successful}; expected ≥1 rate limited, got {rate_limited}"
                )
            else:
                logger.info(
                    f"✓ {config.endpoint}: {successful} successful, {rate_limited} rate limited"
                )
            
            # Test headers
            headers_valid = self.verify_rate_limit_headers(headers, config)
            endpoint_results["headers_valid"] = headers_valid
            if not headers_valid:
                summary["all_passed"] = False
            
            # Test Retry-After header
            retry_after_valid = await self.test_retry_after_header(config)
            endpoint_results["retry_after"] = retry_after_valid
            if not retry_after_valid:
                summary["all_passed"] = False
            
            # Test reset (optional, takes 65+ seconds)
            if not skip_reset_test:
                reset_works = await self.test_reset_after_timeout(config)
                endpoint_results["reset_works"] = reset_works
                if not reset_works:
                    summary["all_passed"] = False
            else:
                logger.info(f"\n⊘ Skipping reset test for {config.endpoint} (takes 65+ seconds)")
                endpoint_results["reset_works"] = "skipped"
            
            summary["endpoints"][config.endpoint] = endpoint_results
        
        # Test multi-IP
        multi_ip_passed = await self.test_multi_ip_independent_limits()
        summary["multi_ip"] = multi_ip_passed
        if not multi_ip_passed:
            summary["all_passed"] = False
        
        return summary

    def print_summary(self, summary: Dict):
        """Print test summary."""
        logger.info("\n" + "="*70)
        logger.info("TEST SUMMARY")
        logger.info("="*70)
        
        for endpoint, results in summary["endpoints"].items():
            logger.info(f"\n{endpoint}:")
            
            at_limit = results["at_limit"]
            status = "✓" if at_limit["passed"] else "✗"
            logger.info(
                f"  {status} At Limit: {at_limit['successful']}/{at_limit['expected_limit']} "
                f"successful, {at_limit['rate_limited']} rate limited"
            )
            
            headers_status = "✓" if results["headers_valid"] else "✗"
            logger.info(f"  {headers_status} Headers Valid: {results['headers_valid']}")
            
            retry_status = "✓" if results["retry_after"] else "✗"
            logger.info(f"  {retry_status} Retry-After Header: {results['retry_after']}")
            
            if results["reset_works"] != "skipped":
                reset_status = "✓" if results["reset_works"] else "✗"
                logger.info(f"  {reset_status} Reset Works: {results['reset_works']}")
            else:
                logger.info("  ⊘ Reset Works: skipped")
        
        logger.info(f"\nMulti-IP Independent Limits: {'✓' if summary['multi_ip'] else '✗'}")
        
        logger.info("\n" + "="*70)
        if summary["all_passed"]:
            logger.info("✓ ALL TESTS PASSED")
        else:
            logger.info("✗ SOME TESTS FAILED")
        logger.info("="*70)


async def main():
    """Main entry point."""
    import sys
    
    # Check if server is running
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BASE_URL}/")
            if response.status_code not in [200, 404]:
                logger.error(f"Server health check failed: {response.status_code}")
                sys.exit(1)
    except Exception as e:
        logger.error(f"Cannot connect to server at {BASE_URL}: {e}")
        logger.error("Make sure the backend is running: python -m backend")
        sys.exit(1)
    
    # Run tests
    tester = RateLimitTester(BASE_URL)
    
    # Skip reset test by default (takes 65+ seconds per endpoint)
    skip_reset = "--no-skip-reset" not in sys.argv
    
    summary = await tester.run_all_tests(skip_reset_test=skip_reset)
    tester.print_summary(summary)
    
    # Exit with appropriate code
    sys.exit(0 if summary["all_passed"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
