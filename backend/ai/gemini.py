"""Google Gemini AI provider for PolyEdge 5-forecaster ensemble."""
import httpx

from backend.config import settings

from loguru import logger
class GeminiProvider:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")
        self.model = getattr(settings, "GEMINI_MODEL", "gemini-1.5-pro")
        self.enabled = bool(self.api_key) and getattr(settings, "GEMINI_ENABLED", False)

    async def predict(self, prompt: str) -> dict:
        if not self.enabled:
            return {"probability": 0.5, "confidence": 0.0, "source": "gemini_disabled"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    params={"key": self.api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.1},
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                prob = self._extract_probability(text)
                return {"probability": prob, "confidence": 0.5, "source": "gemini"}
        except Exception as e:
            logger.warning(f"Gemini API call failed: {e}")
            return {"probability": 0.5, "confidence": 0.0, "source": "gemini_error"}

    @staticmethod
    def _extract_probability(text: str) -> float:
        import re
        match = re.search(r"(\d+\.?\d*)", text)
        if match:
            prob = float(match.group(1))
            if 0 <= prob <= 1:
                return prob
            if 0 <= prob <= 100:
                return prob / 100.0
        return 0.5
