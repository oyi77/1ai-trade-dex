from backend.ai.base_provider import BaseAIProvider, ProviderManifest
from backend.ai.provider_registry import provider_registry


@provider_registry.plugin
class GeminiProvider(BaseAIProvider):
    @classmethod
    def manifest(cls):
        return ProviderManifest(
            name="gemini",
            display_name="Google Gemini",
            version="1.0.0",
            supports_streaming=False,
            supports_tool_use=False,
            max_tokens=8192,
            required_env_vars=["GEMINI_API_KEY"],
            cost_per_1k_tokens_usd=0.001,
            tags=["google", "mid-tier"],
        )

    async def complete(self, prompt, system=None, max_tokens=1000, temperature=0.7, **kwargs):
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent",
                params={"key": kwargs.get("api_key", "")},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
