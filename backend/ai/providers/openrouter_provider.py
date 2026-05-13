from backend.ai.base_provider import BaseAIProvider, ProviderManifest
from backend.ai.provider_registry import provider_registry


@provider_registry.plugin
class OpenRouterProvider(BaseAIProvider):
    @classmethod
    def manifest(cls):
        return ProviderManifest(
            name="openrouter",
            display_name="OpenRouter",
            version="1.0.0",
            supports_streaming=True,
            supports_tool_use=True,
            max_tokens=128000,
            required_env_vars=["OPENROUTER_API_KEY"],
            cost_per_1k_tokens_usd=0.001,
            tags=["aggregator", "multi-model"],
        )

    async def complete(self, prompt, system=None, max_tokens=1000, temperature=0.7, **kwargs):
        import httpx
        model = kwargs.get("model", "openai/gpt-4o-mini")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {kwargs.get('api_key', '')}",
                    "HTTP-Referer": "https://polyedge.io",
                    "X-Title": "PolyEdge Trading Bot",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
