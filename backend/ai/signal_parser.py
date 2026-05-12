"""Signal Parser for MiroFish Integration.

Converts MiroFish API responses to internal Signal format and integrates with
the debate engine for weighted multi-agent consensus voting.

Key Features:
- Parse MiroFish signals to internal Signal dataclass
- Validate prediction and confidence ranges (0.0-1.0)
- Aggregate MiroFish signals with existing strategy signals
- Store signals in database (upsert pattern)
- Error handling: malformed signals logged and skipped (no crash)
- MiroFish signals are "advisory" - weighted votes, not directives
- Configurable signal weight via settings (default 1.0)
"""

from loguru import logger
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Signal:
    """Internal signal format for debate engine integration."""
    market_id: str
    prediction: float  # 0.0-1.0
    confidence: float  # 0.0-1.0
    source: str  # e.g., "mirofish_prediction", "btc_oracle", "weather_emos"
    reasoning: str
    weight: float = 1.0  # Default weight; configurable per signal type


class SignalParser:
    """Parses MiroFish API responses and integrates with debate engine."""

    def __init__(self):
        """Initialize signal parser."""
        from backend.core.config_service import get_setting

        self.mirofish_signal_weight = get_setting("MIROFISH_SIGNAL_WEIGHT", 1.0)
        logger.info(
            f"SignalParser initialized with MiroFish weight={self.mirofish_signal_weight}"
        )

    def parse_mirofish_signal(self, raw_signal: Dict[str, Any]) -> Optional[Signal]:
        """Convert MiroFish API response to internal Signal format.

        Args:
            raw_signal: Raw MiroFish signal from API (dict with market_id, prediction, confidence, reasoning)

        Returns:
            Signal object if valid, None if parsing fails (logged and skipped)

        Raises:
            None - errors are caught and logged
        """
        try:
            # Extract and validate required fields
            market_id = raw_signal.get("market_id")
            prediction = raw_signal.get("prediction")
            confidence = raw_signal.get("confidence")
            reasoning = raw_signal.get("reasoning", "")
            source = raw_signal.get("source", "mirofish_prediction")

            # Validate presence of required fields
            if market_id is None:
                logger.warning("MiroFish signal missing market_id - skipping")
                return None

            if prediction is None:
                logger.warning(f"MiroFish signal for {market_id} missing prediction - skipping")
                return None

            if confidence is None:
                logger.warning(f"MiroFish signal for {market_id} missing confidence - skipping")
                return None

            # Convert to float
            try:
                prediction = float(prediction)
                confidence = float(confidence)
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"MiroFish signal {market_id}: failed to convert to float: {e} "
                    f"(prediction={prediction}, confidence={confidence})"
                )
                return None

            # Validate market_id is not empty
            if not str(market_id).strip():
                logger.warning("MiroFish signal has empty market_id - skipping")
                return None

            if not (0.0 <= prediction <= 1.0):
                logger.warning(
                    f"MiroFish signal {market_id}: prediction {prediction} out of range [0.0, 1.0]"
                )
                return None

            if not (0.0 <= confidence <= 1.0):
                logger.warning(
                    f"MiroFish signal {market_id}: confidence {confidence} out of range [0.0, 1.0]"
                )
                return None

            # Create and return Signal object
            signal = Signal(
                market_id=str(market_id),
                prediction=prediction,
                confidence=confidence,
                source=source,
                reasoning=str(reasoning),
                weight=self.mirofish_signal_weight,
            )

            logger.info(
                f"Parsed MiroFish signal: market={signal.market_id}, "
                f"prediction={signal.prediction:.2f}, confidence={signal.confidence:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(
                f"Unexpected error parsing MiroFish signal: {e}",
                exc_info=True,
                extra={"raw_signal": raw_signal}
            )
            return None

    def parse_mirofish_signals(self, signals: List[Dict[str, Any]]) -> List[Signal]:
        """Parse list of MiroFish signals.

        Args:
            signals: List of raw MiroFish signals from API

        Returns:
            List of valid Signal objects (skips invalid ones)
        """
        parsed_signals = []

        for raw_signal in signals:
            signal = self.parse_mirofish_signal(raw_signal)
            if signal:
                parsed_signals.append(signal)

        logger.info(
            f"Parsed {len(parsed_signals)}/{len(signals)} MiroFish signals "
            f"({len(signals) - len(parsed_signals)} skipped)"
        )

        return parsed_signals

    def aggregate_signals(
        self,
        mirofish_signals: List[Signal],
        existing_signals: Optional[List[Signal]] = None,
    ) -> List[Signal]:
        """Combine MiroFish predictions with existing strategy signals.

        Args:
            mirofish_signals: List of parsed MiroFish Signal objects
            existing_signals: List of existing signals from other strategies (optional)

        Returns:
            Merged list of all signals for debate engine input

        Logic:
            - MiroFish signals are "advisory" - weighted votes, not directives
            - Combine with existing signals (BTC Oracle, Weather EMOS, Copy Trader, etc.)
            - All signals have equal standing in debate (weight determines influence)
            - Example: 3 strategies vote "long" + MiroFish 0.75 bullish = consensus with higher conviction
        """
        if existing_signals is None:
            existing_signals = []

        # Merge lists - MiroFish first (easier to track), then existing
        all_signals = mirofish_signals + existing_signals

        logger.info(
            f"Aggregated signals: {len(mirofish_signals)} from MiroFish + "
            f"{len(existing_signals)} existing = {len(all_signals)} total"
        )

        return all_signals

    def store_signal_in_db(self, signal: Signal, session=None) -> bool:
        """Store parsed signal in MiroFishSignal table (upsert pattern).

        Args:
            signal: Parsed Signal object to store
            session: SQLAlchemy session (uses get_db_session() if None)

        Returns:
            True if stored successfully, False on error

        Logic:
            - Updates existing row if market_id exists (upsert)
            - Inserts new row if market_id is new
            - Logs success/failure
        """
        try:
            if session is None:
                from backend.models.database import get_db_session
                session = get_db_session()

            from backend.models.database import MiroFishSignal

            # Check if signal already exists for this market
            existing = session.query(MiroFishSignal).filter(
                MiroFishSignal.market_id == signal.market_id
            ).first()

            if existing:
                # Update existing signal (upsert)
                existing.prediction = signal.prediction
                existing.confidence = signal.confidence
                existing.reasoning = signal.reasoning
                existing.source = signal.source
                existing.weight = signal.weight
                existing.updated_at = datetime.now(timezone.utc)

                logger.info(f"Updated MiroFish signal for {signal.market_id}")
            else:
                # Insert new signal
                new_signal = MiroFishSignal(
                    market_id=signal.market_id,
                    prediction=signal.prediction,
                    confidence=signal.confidence,
                    reasoning=signal.reasoning,
                    source=signal.source,
                    weight=signal.weight,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(new_signal)

                logger.info(f"Inserted new MiroFish signal for {signal.market_id}")

            session.commit()
            return True

        except Exception as e:
            logger.error(
                f"Failed to store signal {signal.market_id} in database: {e}",
                exc_info=True
            )
            if session:
                session.rollback()
            return False

    def store_signals_batch(
        self,
        signals: List[Signal],
        session=None,
    ) -> Dict[str, Any]:
        """Store batch of signals in database.

        Args:
            signals: List of Signal objects to store
            session: SQLAlchemy session (uses get_db_session() if None)

        Returns:
            Dict with success/failure counts:
            {
                "total": 10,
                "successful": 9,
                "failed": 1,
                "messages": ["Signal for market_id_1 stored", ...]
            }
        """
        results = {
            "total": len(signals),
            "successful": 0,
            "failed": 0,
            "messages": [],
        }

        for signal in signals:
            if self.store_signal_in_db(signal, session):
                results["successful"] += 1
                results["messages"].append(f"✓ {signal.market_id}")
            else:
                results["failed"] += 1
                results["messages"].append(f"✗ {signal.market_id}")

        logger.info(
            f"Batch signal storage: {results['successful']}/{results['total']} "
            f"successful, {results['failed']} failed"
        )

        return results


# Singleton instance for convenience
_parser: Optional[SignalParser] = None


def get_signal_parser() -> SignalParser:
    """Get or create singleton SignalParser instance."""
    global _parser
    if _parser is None:
        _parser = SignalParser()
    return _parser


def reset_signal_parser() -> None:
    """Reset singleton parser (useful for testing)."""
    global _parser
    _parser = None
