"""MiroFish API Client for prediction signal integration.

Fetches AI-powered prediction signals from MiroFish API with resilience patterns:
- Exponential backoff retry logic
- Timeout handling
- Circuit breaker preparation
- Fallback to empty list on failure
- Dynamic settings integration
"""

import httpx
import time
from loguru import logger
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


@dataclass
class MiroFishSignal:
    """MiroFish prediction signal."""
    market_id: str
    prediction: float  # 0.0-1.0
    confidence: float  # 0.0-1.0
    reasoning: str
    source: str = "mirofish"


@dataclass
class ErrorResponse:
    """Structured error response for fallback handling."""
    error_type: str
    message: str
    timestamp: str
    traceback: Optional[str] = None


class MiroFishClient:
    """Client for fetching prediction signals from MiroFish API.

    Features:
    - Exponential backoff retry (1s → 5s → 10s, max 3 retries)
    - Timeout handling via MIROFISH_API_TIMEOUT setting
    - Circuit breaker tracking (consecutive failures)
    - Graceful fallback (returns empty list on failure)
    - Dynamic config reload from settings
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """Initialize MiroFish client.

        Priority: Database → Environment Variables → Defaults

        Args:
            api_url: MiroFish API base URL (from settings if None)
            api_key: API authentication key (from settings if None)
            timeout: Request timeout in seconds (from settings if None)
        """
        import os
        from backend.models.database import SystemSettings
        from backend.config_extensions import settings as extended_settings

        # Initialize with provided values or defaults
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout

        # Try to read from database first
        db_source = None
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                # Query database for credentials
                if not self.api_url:
                    db_url = db.query(SystemSettings).filter(
                        SystemSettings.key == "mirofish_api_url"
                    ).first()
                    if db_url:
                        self.api_url = db_url.value
                        db_source = "database"

                if not self.api_key:
                    db_key = db.query(SystemSettings).filter(
                        SystemSettings.key == "mirofish_api_key"
                    ).first()
                    if db_key:
                        self.api_key = db_key.value
                        if not db_source:
                            db_source = "database"

                if not self.timeout:
                    db_timeout = db.query(SystemSettings).filter(
                        SystemSettings.key == "mirofish_api_timeout"
                    ).first()
                    if db_timeout:
                        self.timeout = float(db_timeout.value)
                        if not db_source:
                            db_source = "database"
        except Exception as e:
            logger.warning(f"Failed to read MiroFish settings from database: {e}")

        # Fall back to extended settings system
        extended_source = None
        if not self.api_url:
            self.api_url = extended_settings.MIROFISH_API_URL
            if self.api_url:
                extended_source = "extended_settings"

        if not self.api_key:
            self.api_key = extended_settings.MIROFISH_API_KEY
            if self.api_key and not extended_source:
                extended_source = "extended_settings"

        if not self.timeout:
            timeout_extended = extended_settings.MIROFISH_API_TIMEOUT
            if timeout_extended:
                try:
                    self.timeout = float(timeout_extended)
                    if not extended_source:
                        extended_source = "extended_settings"
                except ValueError:
                    logger.warning(f"Invalid MIROFISH_API_TIMEOUT in settings: {timeout_extended}")

        # Finally fall back to environment variables (legacy support)
        env_source = None
        if not self.api_url:
            self.api_url = os.getenv("MIROFISH_API_URL")
            if self.api_url:
                env_source = "environment"

        if not self.api_key:
            self.api_key = os.getenv("MIROFISH_API_KEY")
            if self.api_key and not env_source:
                env_source = "environment"

        if not self.timeout:
            timeout_env = os.getenv("MIROFISH_API_TIMEOUT")
            if timeout_env:
                try:
                    self.timeout = float(timeout_env)
                    if not env_source:
                        env_source = "environment"
                except ValueError:
                    logger.warning(f"Invalid MIROFISH_API_TIMEOUT env var: {timeout_env}")

        # Apply defaults
        if not self.api_url:
            from backend.config import settings as _s
            self.api_url = _s.MIROFISH_API_URL
        if not self.api_key:
            self.api_key = ""
        if not self.timeout:
            self.timeout = 30.0

        # Log which source was used
        source_msg = db_source or extended_source or env_source or "defaults"
        logger.info(
            f"MiroFish client initialized: url={self.api_url}, timeout={self.timeout}s, "
            f"credentials_source={source_msg}"
        )

        self._client: Optional[httpx.AsyncClient] = None
        self._consecutive_failures = 0
        self._circuit_open = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=headers,
            )
        return self._client

    async def close(self):
        """Close HTTP client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(
        self,
        market: str = "polymarket",
        question: str = "",
        market_price: float = 0.0,
    ) -> List[MiroFishSignal]:
        """Fetch prediction signals from MiroFish API.

        Args:
            market: Market platform filter (default: "polymarket")

        Returns:
            List of MiroFishSignal objects. Returns empty list on failure.

        Raises:
            TimeoutError: If request exceeds MIROFISH_API_TIMEOUT
        """
        if self._circuit_open:
            logger.warning("Circuit breaker OPEN - skipping MiroFish API call")
            return []

        if self._consecutive_failures >= 5:
            self._circuit_open = True
            logger.error(
                f"Circuit breaker triggered after {self._consecutive_failures} failures"
            )
            return []

        endpoint = f"{self.api_url}/api/simulation/signals"
        params = {"market": market}
        if question:
            params["question"] = question
        if market_price > 0:
            params["market_price"] = str(market_price)

        # Retry logic with exponential backoff
        retry_delays = [1.0, 5.0, 10.0]
        last_error = None

        for attempt, delay in enumerate(retry_delays, 1):
            try:
                start_time = time.time()
                client = await self._get_client()

                logger.info(
                    f"Fetching MiroFish signals (attempt {attempt}/{len(retry_delays)}): "
                    f"{endpoint}?market={market}"
                )

                response = await client.get(endpoint, params=params)
                response.raise_for_status()

                elapsed = time.time() - start_time
                data = response.json()

                # Parse response
                signals = self._parse_signals(data)

                # Reset failure counter on success
                self._consecutive_failures = 0

                try:
                    from backend.services.mirofish_service import get_mirofish_service
                    get_mirofish_service().record_signal_fetch(len(signals))
                except Exception:
                    logger.exception("Failed to record MiroFish signal fetch")

                logger.info(
                    f"MiroFish API success: {len(signals)} signals fetched "
                    f"in {elapsed:.2f}s"
                )

                return signals

            except httpx.TimeoutException as e:
                last_error = e
                self._consecutive_failures += 1
                logger.warning(
                    f"MiroFish API timeout (attempt {attempt}): {e}",
                    exc_info=True
                )

                if attempt < len(retry_delays):
                    logger.info(f"Retrying in {delay}s...")
                    await self._async_sleep(delay)

            except httpx.HTTPStatusError as e:
                last_error = e
                self._consecutive_failures += 1
                logger.error(
                    f"MiroFish API HTTP error (attempt {attempt}): "
                    f"status={e.response.status_code}, body={e.response.text}",
                    exc_info=True
                )

                # Don't retry on 4xx client errors
                if 400 <= e.response.status_code < 500:
                    break

                if attempt < len(retry_delays):
                    logger.info(f"Retrying in {delay}s...")
                    await self._async_sleep(delay)

            except Exception as e:
                last_error = e
                self._consecutive_failures += 1
                logger.error(
                    f"MiroFish API unexpected error (attempt {attempt}): {e}",
                    exc_info=True
                )

                if attempt < len(retry_delays):
                    logger.info(f"Retrying in {delay}s...")
                    await self._async_sleep(delay)

        self.handle_api_error(last_error)
        logger.warning(
            f"MiroFish API failed after {len(retry_delays)} attempts - "
            f"returning empty list (fallback mode)"
        )

        return []

    def _parse_signals(self, data: Dict[str, Any]) -> List[MiroFishSignal]:
        """Parse API response into MiroFishSignal objects.

        Args:
            data: Raw API response JSON

        Returns:
            List of validated MiroFishSignal objects
        """
        signals = []
        raw_signals = data.get("signals", [])

        for raw_signal in raw_signals:
            if self.validate_signal(raw_signal):
                try:
                    signal = MiroFishSignal(
                        market_id=raw_signal["market_id"],
                        prediction=float(raw_signal["prediction"]),
                        confidence=float(raw_signal["confidence"]),
                        reasoning=raw_signal.get("reasoning", ""),
                        source=raw_signal.get("source", "mirofish"),
                    )
                    signals.append(signal)
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse signal: {e}, data={raw_signal}")
                    continue
            else:
                logger.warning(f"Invalid signal skipped: {raw_signal}")

        return signals

    def validate_signal(self, signal: Dict[str, Any]) -> bool:
        """Validate signal has required fields and valid types.

        Args:
            signal: Raw signal dictionary from API

        Returns:
            True if signal is valid, False otherwise
        """
        required_fields = ["market_id", "prediction", "confidence"]

        # Check required fields present
        for field in required_fields:
            if field not in signal:
                logger.debug(f"Signal missing required field: {field}")
                return False

        # Validate types and ranges
        try:
            prediction = float(signal["prediction"])
            confidence = float(signal["confidence"])

            if not (0.0 <= prediction <= 1.0):
                logger.debug(f"Prediction out of range: {prediction}")
                return False

            if not (0.0 <= confidence <= 1.0):
                logger.debug(f"Confidence out of range: {confidence}")
                return False

            if not isinstance(signal["market_id"], str) or not signal["market_id"]:
                logger.debug(f"Invalid market_id: {signal['market_id']}")
                return False

        except (ValueError, TypeError) as e:
            logger.debug(f"Type validation failed: {e}")
            return False

        return True

    def handle_api_error(self, error: Exception) -> ErrorResponse:
        """Handle API error with structured logging and response.

        Args:
            error: Exception that occurred

        Returns:
            ErrorResponse with error details
        """
        import traceback

        error_type = type(error).__name__
        message = str(error)
        tb = traceback.format_exc()

        logger.error(
            f"MiroFish API error handled: type={error_type}, message={message}",
            exc_info=True,
            extra={
                "error_type": error_type,
                "consecutive_failures": self._consecutive_failures,
                "circuit_open": self._circuit_open,
            }
        )

        return ErrorResponse(
            error_type=error_type,
            message=message,
            timestamp=datetime.now(timezone.utc).isoformat(),
            traceback=tb,
        )

    async def _async_sleep(self, seconds: float):
        """Async sleep helper for retry delays."""
        import asyncio
        await asyncio.sleep(seconds)

    def reset_circuit_breaker(self):
        """Manually reset circuit breaker (for testing or recovery)."""
        self._circuit_open = False
        self._consecutive_failures = 0
        logger.info("Circuit breaker manually reset")
