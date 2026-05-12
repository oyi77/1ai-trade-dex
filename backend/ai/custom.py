"""Custom / OmniRoute AI provider using OpenAI-compatible chat completions API."""
import time
import re
import json
from loguru import logger
from typing import Optional, Dict, Any, List

from .base import AIAnalysis, BaseAIClient, create_classification_prompt


class CustomAIClient(BaseAIClient):
    """
    OpenAI-compatible AI client.
    Works with OmniRoute, any OpenAI-compatible proxy, or direct OpenAI/Azure endpoints.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider_name: str = "custom",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model or "gpt-4o-mini"
        self.provider_name = provider_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError("openai package not installed. Run: pip install openai")
            kwargs: Dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            else:
                # openai requires a non-empty api_key; use placeholder for local servers
                kwargs["api_key"] = "no-key"
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def _chat(self, prompt: str, max_tokens: int = 400, temperature: float = 0.2) -> tuple[str, float, int]:
        """Single chat completion. Returns (content, latency_ms, tokens_used)."""
        start = time.time()
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency_ms = (time.time() - start) * 1000
        content = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return content.strip(), latency_ms, tokens

    async def classify_market(self, title: str, description: str = "") -> tuple[str, float]:
        try:
            prompt = create_classification_prompt(title, description)
            result, _, _ = self._chat(prompt, max_tokens=20, temperature=0.1)
            parts = result.lower().split(",")
            category = parts[0].strip()
            confidence = 0.7
            if len(parts) > 1:
                try:
                    confidence = int(parts[1].strip()) / 100
                except ValueError:
                    pass
            valid = ["weather", "crypto", "politics", "economics", "sports", "other"]
            if category not in valid:
                for c in valid:
                    if c in result.lower():
                        category = c
                        break
                else:
                    category = "other"
            return (category, min(1.0, max(0.0, confidence)))
        except Exception as e:
            logger.error(f"{self.provider_name} classification failed: {e}")
            return ("other", 0.0)

    async def analyze_signal(
        self, signal_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> AIAnalysis:
        start = time.time()
        try:
            prompt = (
                f"Briefly analyze this trading signal (1-2 sentences):\n\n"
                f"Market: {signal_data.get('market_title', 'Unknown')}\n"
                f"Edge: {signal_data.get('edge', 0):.1%}\n"
                f"Direction: {signal_data.get('direction', 'Unknown')}\n\n"
                f"Is this edge reliable?"
            )
            result, latency_ms, tokens = self._chat(prompt, max_tokens=100, temperature=0.3)
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
                provider=self.provider_name,
                latency_ms=latency_ms,
                tokens_used=tokens,
            )
        except Exception as e:
            logger.error(f"{self.provider_name} analysis failed: {e}")
            return AIAnalysis(
                reasoning=f"Analysis unavailable: {e}",
                confidence=0.0,
                model_used=self.model,
                provider=self.provider_name,
                latency_ms=(time.time() - start) * 1000,
            )

    async def detect_anomalies(self, markets: List[Dict[str, Any]]) -> List:
        return []

    def suggest_params(self, prompt: str) -> tuple[Dict[str, Any], str]:
        """Call provider for parameter suggestions. Returns (suggestions_dict, raw_response)."""
        raw, _, _ = self._chat(prompt, max_tokens=400, temperature=0.2)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            suggestions = json.loads(json_match.group())
        else:
            suggestions = json.loads(raw)
        return suggestions, raw


def get_custom_client() -> Optional[CustomAIClient]:
    """Build a CustomAIClient from current settings, or return None if not configured."""
    from backend.config import settings
    provider = getattr(settings, "AI_PROVIDER", "groq")
    if provider not in ("omniroute", "custom"):
        return None
    api_key = getattr(settings, "AI_API_KEY", None)
    base_url = getattr(settings, "AI_BASE_URL", None)
    model = getattr(settings, "AI_MODEL", None)
    if not base_url:
        return None
    return CustomAIClient(
        api_key=api_key,
        base_url=base_url,
        model=model or "gpt-4o-mini",
        provider_name=provider,
    )
