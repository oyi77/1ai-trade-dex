"""Groq AI provider plugin wrapping GroqClassifier for the plugin system."""
import os
from typing import Optional

from backend.ai.base_provider import BaseAIProvider, ProviderManifest
from backend.ai.groq import GroqClassifier
from backend.ai.provider_registry import provider_registry


@provider_registry.plugin
class GroqProvider(BaseAIProvider, GroqClassifier):
    """Groq AI provider plugin registered in the AI provider registry.

    Wraps the existing GroqClassifier to conform to the BaseAIProvider interface,
    enabling registration in the plugin system with automatic discovery.
    """

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY", "")
        model = os.environ.get("GROQ_MODEL", "llama-3.1-70b-versatile")
        GroqClassifier.__init__(self, api_key=api_key or None, model=model)

    @classmethod
    def manifest(cls) -> ProviderManifest:
        return ProviderManifest(
            name="groq",
            display_name="Groq",
            version="1.0.0",
            supports_streaming=False,
            supports_tool_use=False,
            max_tokens=8192,
            required_env_vars=["GROQ_API_KEY"],
            cost_per_1k_tokens_usd=0.0005,
            tags=["primary", "llm", "fast"],
        )

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        """Execute a completion via GroqClassifier.

        Uses classify_market for simple queries and extract_market_details
        for structured extraction. Falls back to a generic completion path.
        """
        if "classify" in prompt.lower() or "category" in prompt.lower():
            category, confidence = self.classify_market(prompt)
            return f"Category: {category} (confidence: {confidence:.2f})"

        # For general prompts, use the Groq chat completion directly
        try:
            client = self._get_client()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return ""