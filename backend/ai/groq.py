"""Groq AI integration for fast market classification and parsing."""

import time
import re
from typing import Optional, Dict, Any, List
from loguru import logger

from .base import AIAnalysis, BaseAIClient, create_classification_prompt
from .logger import get_ai_logger


class GroqClassifier(BaseAIClient):
    """
    Groq-powered classifier for:
    - Fast market categorization
    - Quick title parsing
    - Rapid detail extraction
    """

    def __init__(
        self, api_key: Optional[str] = None, model: str = "llama-3.1-70b-versatile"
    ):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy load the async Groq client."""
        if self._client is None:
            if not self.api_key:
                from backend.config import settings

                self.api_key = settings.GROQ_API_KEY

            if not self.api_key:
                raise ValueError("GROQ_API_KEY not configured")

            try:
                from groq import AsyncGroq

                self._client = AsyncGroq(api_key=self.api_key)
            except ImportError:
                raise ImportError("groq package not installed. Run: pip install groq")

        return self._client

    async def classify_market(
        self, title: str, description: str = ""
    ) -> tuple[str, float]:
        """
        Quickly classify a market into a category using Groq.

        Args:
            title: Market title
            description: Optional market description

        Returns:
            (category, confidence) tuple
        """
        start_time = time.time()

        try:
            client = self._get_client()
            prompt = create_classification_prompt(title, description)

            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.1,
            )

            result = response.choices[0].message.content.strip().lower()
            latency_ms = (time.time() - start_time) * 1000
            tokens_used = response.usage.total_tokens if response.usage else 0

            logger.debug(
                f"Groq classification: '{title[:30]}...' -> {result} ({latency_ms:.0f}ms)"
            )

            try:
                ai_logger = get_ai_logger()
                ai_logger.log_call(
                    provider="groq",
                    model=self.model,
                    prompt=prompt,
                    response=result,
                    latency_ms=latency_ms,
                    tokens_used=tokens_used,
                    call_type="classification",
                    success=True,
                )
            except Exception as e:
                logger.warning(f"Failed to log classification: {e}")

            # Parse response
            parts = result.split(",")
            category = parts[0].strip()
            confidence = 0.7

            if len(parts) > 1:
                try:
                    confidence = int(parts[1].strip()) / 100
                except ValueError:
                    pass

            # Validate category
            valid_categories = [
                "weather",
                "crypto",
                "politics",
                "economics",
                "sports",
                "other",
            ]
            if category not in valid_categories:
                # Try to find a valid category in the response
                for cat in valid_categories:
                    if cat in result:
                        category = cat
                        break
                else:
                    category = "other"

            return (category, min(1.0, max(0.0, confidence)))

        except Exception as e:
            logger.error(f"Groq classification failed: {e}")
            return ("other", 0.0)

    async def extract_market_details(self, title: str) -> Dict[str, Any]:
        """
        Extract structured details from a market title.

        Returns dict with keys like:
        - threshold: numeric threshold if applicable
        - direction: "above" or "below"
        - asset: crypto symbol, city name, economic indicator
        - timeframe: date or period
        """
        start_time = time.time()

        try:
            client = self._get_client()

            prompt = f"""Extract details from this prediction market title:

"{title}"

Respond in this exact format (use N/A if not found):
threshold: <number or N/A>
direction: <above/below/N/A>
asset: <asset name or N/A>
timeframe: <date/period or N/A>"""

            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.1,
            )

            result = response.choices[0].message.content.strip()
            latency_ms = (time.time() - start_time) * 1000

            logger.debug(f"Groq extraction ({latency_ms:.0f}ms): {result[:50]}...")

            # Parse response
            details: Dict[str, Any] = {
                "threshold": None,
                "direction": None,
                "asset": None,
                "timeframe": None,
            }

            for line in result.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()

                    if value.lower() != "n/a":
                        if key == "threshold":
                            # Extract numeric value
                            num_match = re.search(r"[\d,\.]+", value)
                            if num_match:
                                try:
                                    details["threshold"] = float(
                                        num_match.group().replace(",", "")
                                    )
                                except ValueError:
                                    pass
                        elif key == "direction":
                            if "above" in value.lower():
                                details["direction"] = "above"
                            elif "below" in value.lower():
                                details["direction"] = "below"
                        elif key in details:
                            details[key] = value

            return details

        except Exception as e:
            logger.error(f"Groq extraction failed: {e}")
            return {
                "threshold": None,
                "direction": None,
                "asset": None,
                "timeframe": None,
            }

    async def analyze_signal(
        self, signal_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> AIAnalysis:
        """
        Quick signal analysis using Groq.
        Less detailed than Claude but much faster.
        """
        start_time = time.time()

        try:
            client = self._get_client()

            prompt = f"""Briefly analyze this trading signal (1-2 sentences):

Market: {signal_data.get("market_title", "Unknown")}
Edge: {signal_data.get("edge", 0):.1%}
Direction: {signal_data.get("direction", "Unknown")}

Key question: Is this edge reliable?"""

            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
            )

            result = response.choices[0].message.content.strip()
            latency_ms = (time.time() - start_time) * 1000
            tokens_used = response.usage.total_tokens if response.usage else 0

            try:
                ai_logger = get_ai_logger()
                ai_logger.log_call(
                    provider="groq",
                    model=self.model,
                    prompt=prompt,
                    response=result,
                    latency_ms=latency_ms,
                    tokens_used=tokens_used,
                    related_market=signal_data.get("market_ticker"),
                    call_type="analysis",
                    success=True,
                )
            except Exception as e:
                logger.debug(f"Failed to log analysis: {e}")

            confidence = 0.6
            if "reliable" in result.lower() or "strong" in result.lower():
                confidence = 0.75
            elif "uncertain" in result.lower() or "risky" in result.lower():
                confidence = 0.4

            return AIAnalysis(
                reasoning=result,
                confidence=confidence,
                raw_response=result,
                model_used=self.model,
                provider="groq",
                latency_ms=latency_ms,
                tokens_used=tokens_used,
            )

        except Exception as e:
            logger.error(f"Groq analysis failed: {e}")
            return AIAnalysis(
                reasoning=f"Analysis unavailable: {e}",
                confidence=0.0,
                model_used=self.model,
                provider="groq",
                latency_ms=(time.time() - start_time) * 1000,
            )

    async def detect_anomalies(self, markets: List[Dict[str, Any]]) -> List:
        """Groq is not used for anomaly detection - use Claude instead."""
        return []


_KEYWORD_MAP = {
    "weather": [
        "temperature",
        "rain",
        "snow",
        "wind",
        "forecast",
        "celsius",
        "fahrenheit",
        "storm",
        "hurricane",
    ],
    "crypto": [
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "crypto",
        "token",
        "defi",
        "nft",
        "solana",
        "sol",
    ],
    "politics": [
        "election",
        "vote",
        "president",
        "congress",
        "senate",
        "governor",
        "bill",
        "policy",
        "trump",
        "biden",
    ],
    "economics": [
        "gdp",
        "inflation",
        "unemployment",
        "fed",
        "interest rate",
        "cpi",
        "recession",
        "treasury",
        "fed funds",
    ],
    "sports": [
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "soccer",
        "championship",
        "super bowl",
        "world cup",
        "playoff",
    ],
}


def _keyword_classify(title: str, description: str = "") -> tuple[str, float]:
    combined = f"{title} {description}".lower()
    for category, keywords in _KEYWORD_MAP.items():
        if any(kw in combined for kw in keywords):
            return (category, 0.5)
    return ("other", 0.3)


async def classify_with_fallback(
    title: str, description: str = "", groq_client: Optional[GroqClassifier] = None
) -> tuple[str, float]:
    if groq_client:
        try:
            return await groq_client.classify_market(title, description)
        except Exception as e:
            logger.warning(f"Groq failed, using keyword fallback: {e}")

    return _keyword_classify(title, description)
