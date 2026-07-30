"""AGI system, AI providers, blockchain, and bot settings."""
from dataclasses import dataclass
from .system import AGISystemMixin
from .agi_core import AGICoreMixin
from .ai_providers import AIProvidersMixin
from .blockchain import BlockchainMixin
from .misc import AGIMiscMixin


@dataclass
class AGIMixin(  # noqa: F811 — backward compat
    AGISystemMixin,
    AGICoreMixin,
    AIProvidersMixin,
    BlockchainMixin,
    AGIMiscMixin,
):
    """Aggregate AGI mixin (all sub-mixins combined)."""
    pass


__all__ = [
    "AGIMixin", "AGISystemMixin", "AGICoreMixin",
    "AIProvidersMixin", "BlockchainMixin", "AGIMiscMixin",
]
