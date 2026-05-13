"""
Test circuit breaker behavior with simulated failures.

Simulates 5 database failures to open the circuit, then verifies requests fail fast.
"""

import asyncio
import logging
from sqlalchemy.exc import OperationalError
import pybreaker
from backend.core.circuit_breaker_pybreaker import (
    db_breaker,
    get_breaker_status
)

logging.basicConfig(level=logging.INFO)
from loguru import logger


def failing_db_query():
    """Simulates a failing database query."""
    raise OperationalError("Connection refused", None, None)


def successful_db_query():
    """Simulates a successful database query."""
    return "SUCCESS"


async def test_db_circuit_breaker():
    """Test database circuit breaker opens after 5 failures."""
    logger.info("=== Testing Database Circuit Breaker ===")
    
    logger.info("Simulating 5 database failures...")
    for i in range(5):
        try:
            db_breaker.call(failing_db_query)
        except (OperationalError, pybreaker.CircuitBreakerError):
            logger.info(f"Failure {i+1}/5 - Circuit state: {db_breaker.current_state}")
    
    logger.info(f"\nCircuit state after 5 failures: {db_breaker.current_state}")
    
    logger.info("\nAttempting query with circuit OPEN (should fail fast)...")
    try:
        db_breaker.call(successful_db_query)
        logger.error("ERROR: Request should have been rejected!")
    except pybreaker.CircuitBreakerError as e:
        logger.info(f"✓ Request rejected: {type(e).__name__}")
    
    logger.info("\nWaiting 60 seconds for circuit to transition to HALF_OPEN...")
    await asyncio.sleep(61)
    
    logger.info(f"Circuit state after timeout: {db_breaker.current_state}")
    
    logger.info("\nAttempting successful query in HALF_OPEN state...")
    try:
        result = db_breaker.call(successful_db_query)
        logger.info(f"✓ Query succeeded: {result}")
        logger.info(f"Circuit state after success: {db_breaker.current_state}")
    except Exception as e:
        logger.error(f"ERROR: Query failed: {e}")


def test_breaker_status():
    """Test circuit breaker status reporting."""
    logger.info("\n=== Testing Circuit Breaker Status ===")
    
    status = get_breaker_status()
    
    for name, info in status.items():
        logger.info(f"\n{name}:")
        logger.info(f"  State: {info['state']}")
        logger.info(f"  Fail Counter: {info['fail_counter']}")
        logger.info(f"  Reset Timeout: {info['reset_timeout']}s")
        logger.info(f"  Fail Max: {info['fail_max']}")


if __name__ == "__main__":
    logger.info("Circuit Breaker Test Suite\n")
    
    test_breaker_status()
    
    logger.info("\n" + "="*60)
    logger.info("Starting circuit breaker failure simulation...")
    logger.info("This will take ~60 seconds to complete.")
    logger.info("="*60 + "\n")
    
    asyncio.run(test_db_circuit_breaker())
    
    logger.info("\n" + "="*60)
    logger.info("Final circuit breaker status:")
    logger.info("="*60)
    test_breaker_status()
    
    logger.info("\n✓ Circuit breaker test complete!")
