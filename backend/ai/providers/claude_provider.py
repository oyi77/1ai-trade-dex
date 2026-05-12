"""Claude AI provider plugin wrapping ClaudeAnalyzer for the plugin system."""
import os
from typing import Optional

from backend.core.plugin_registry import BasePlugin
from backend.ai.base_provider import BaseAIProvider, ProviderManifest
from backend.ai.claude import ClaudeAnalyzer
from backend.ai.provider_registry import provider_registry


@provider_registry.plugin
class ClaudeProvider(BaseAIProvider, ClaudeAnalyzer):
    """Claude AI provider plugin registered in the AI provider registry.

    Wraps the existing ClaudeAnalyzer to conform to the BaseAIProvider interface,
    enabling registration in the plugin system with automatic discovery.
    """

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        ClaudeAnalyzer.__init__(self, api_key=api_key or None, model=model)

    @classmethod
    def manifest(cls) -> ProviderManifest:
        return ProviderManifest(
            name="claude",
            display_name="Anthropic Claude",
            version="1.0.0",
            supports_streaming=False,
            supports_tool_use=True,
            max_tokens=4096,
            required_env_vars=["ANTHROPIC_API_KEY"],
            cost_per_1k_tokens_usd=0.003,
            tags=["primary", "llm", "reasoning"],
        )

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        """Execute a completion via ClaudeAnalyzer.analyze_signal."""
        from backend.ai.base import AIAnalysis

        signal_data = {
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            signal_data["system"] = system

        result: AIAnalysis = await self.analyze_signal(signal_data, kwargs.get("context"))
        return result.reasoning or ""