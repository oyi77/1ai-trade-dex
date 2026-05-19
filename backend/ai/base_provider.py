"""Abstract base class and manifest for AI provider plugins."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProviderManifest:
    """Declarative metadata for an AI provider plugin."""
    name: str
    display_name: str
    version: str
    supports_streaming: bool = False
    supports_tool_use: bool = False
    max_tokens: int = 4096
    required_env_vars: List[str] = field(default_factory=list)
    cost_per_1k_tokens_usd: float = 0.0
    tags: List[str] = field(default_factory=list)


class BaseAIProvider(ABC):
    """Every AI provider plugin must subclass this."""

    @classmethod
    @abstractmethod
    def manifest(cls) -> ProviderManifest:
        """Return static metadata. Called at registration time, before instantiation."""
        ...

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        """Core completion call. Must return the assistant's text response."""
        ...

    async def health_check(self) -> bool:
        """Optional liveness probe. Default: try a minimal completion."""
        try:
            result = await self.complete("ping", max_tokens=5)
            return bool(result)
        except Exception:
            return False

    async def embed(self, text: str) -> List[float]:
        """Optional embedding call. Default returns empty list if provider lacks embedding support."""
        return []

    async def teardown(self) -> None:
        """Clean up AI provider. Override in subclass if needed."""
        pass
