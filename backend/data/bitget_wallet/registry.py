"""Bitget Wallet Web3 provider registry — singleton pattern.

Follows the same pattern as ``crypto_feeds/registry.py``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from backend.core.plugin_registry import PluginRegistry
from backend.data.bitget_wallet.base import (
    BaseBitgetWalletProvider,
    BitgetWalletManifest,
)

logger = logging.getLogger(__name__)

_registry: Optional[BitgetWalletRegistry] = None


class BitgetWalletRegistry(PluginRegistry[BitgetWalletManifest, BaseBitgetWalletProvider]):
    """Singleton registry for Bitget Wallet Web3 providers.

    Use ``get_registry()`` to access the shared instance.
    """

    _instance: Optional["BitgetWalletRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, name: str = "bitget_wallet_registry"):
        if hasattr(self, "_BitgetWalletRegistry__initialized") and self.__initialized:
            return
        super().__init__(name=name)
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton for testing."""
        if cls._instance is not None:
            cls._instance = super(BitgetWalletRegistry, cls).__new__(cls)
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, provider_class: type) -> None:
        """Register a Bitget Wallet provider. Validates manifest and env vars."""
        manifest = provider_class.manifest()
        name = manifest.name

        try:
            from backend.core.registry_utils import check_env_vars
            from backend.core.plugin_errors import PluginEnvVarMissing

            missing = check_env_vars(manifest)
            if missing:
                raise PluginEnvVarMissing(
                    f"Bitget Wallet provider '{name}' requires env vars: {missing}"
                )

            instance = provider_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(
                f"Registered Bitget Wallet provider: {name} v{manifest.version}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to register Bitget Wallet provider {name}: {e}"
            )

    def get_healthy_providers(self) -> List[str]:
        """Return names of providers that passed health check."""
        return [n for n, h in self._health_status.items() if h]

    def get_provider(
        self, name: Optional[str] = None
    ) -> Optional[BaseBitgetWalletProvider]:
        """Get the first healthy provider, or a named one."""
        if name is not None:
            return self._plugins.get(name) if self._enabled.get(name, False) else None
        for n in self.get_healthy_providers():
            return self._plugins.get(n)
        return None


def get_registry() -> BitgetWalletRegistry:
    """Return the singleton BitgetWalletRegistry (lazy init)."""
    global _registry
    if _registry is None:
        _registry = BitgetWalletRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry
    if _registry is not None:
        _registry.reset()
        _registry = None
