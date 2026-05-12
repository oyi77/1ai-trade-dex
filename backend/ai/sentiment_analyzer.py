"""LLM-based sentiment analyzer using existing AI provider."""

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import List

from backend.ai.base import get_ai_client

from loguru import logger
@dataclass
class SentimentResult:
    score: float  # -1.0 (very negative) .. 1.0 (very positive)
    label: str  # positive | negative | neutral
    confidence: float  # 0..1


class SentimentAnalyzer:
    PROMPT_TEMPLATE = (
        "Analyze the sentiment of the following text. Respond ONLY in JSON: "
        '{{"score": float in [-1,1], "label": "positive"|"negative"|"neutral", "confidence": float in [0,1]}}.\n\n'
        "Text: {text}"
    )

    def __init__(self, client=None):
        self.client = client or get_ai_client()

    async def analyze(self, text: str) -> SentimentResult:
        prompt = self.PROMPT_TEMPLATE.format(text=text[:4000])
        try:
            raw = await self._call(prompt)
            data = json.loads(raw)
            return SentimentResult(
                score=float(data.get("score", 0.0)),
                label=str(data.get("label", "neutral")),
                confidence=float(data.get("confidence", 0.0)),
            )
        except Exception as e:
            logger.warning(f"sentiment parse failed: {e}")
            return SentimentResult(score=0.0, label="neutral", confidence=0.0)

    async def _call(self, prompt: str) -> str:
        # Try common AI client interfaces
        if hasattr(self.client, "complete") and inspect.iscoroutinefunction(
            self.client.complete
        ):
            return await self.client.complete(prompt)
        if hasattr(self.client, "complete"):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.client.complete, prompt)
        raise RuntimeError("AI client has no compatible complete() method")

    async def analyze_batch(self, texts: List[str]) -> List[SentimentResult]:
        results = await asyncio.gather(
            *[self.analyze(t) for t in texts], return_exceptions=True
        )
        return [
            r
            if isinstance(r, SentimentResult)
            else SentimentResult(0.0, "neutral", 0.0)
            for r in results
        ]
