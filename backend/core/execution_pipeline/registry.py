"""Generic execution pipeline registry with auto-discovery and mode-based routing.

This module provides the ExecutionPipelineRegistry singleton that manages
execution pipeline stages following the PluginRegistry pattern.
"""

import asyncio
import hashlib
import time
from typing import List, Optional

from loguru import logger

from backend.config import settings

from backend.core.plugin_errors import PluginNotFound
from backend.core.plugin_registry import PluginRegistry

from .base import BaseExecutionStage, ExecutionStageManifest

# Global execution lock — prevents concurrent pipeline runs across strategies
_pipeline_lock = asyncio.Lock()

class ExecutionPipelineRegistry(
    PluginRegistry[ExecutionStageManifest, BaseExecutionStage]
):
    """Singleton registry for execution pipeline stages.

    Manages stages that validate, simulate, execute, record, and notify
    for different trading modes (paper, testnet, live).
    """

    _instance: Optional["ExecutionPipelineRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "execution_pipeline_registry"):
        if self.__initialized:
            return
        super().__init__(name="execution_pipeline_registry")
        self._health_check_interval = 30.0
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(ExecutionPipelineRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def get(self, name: str) -> BaseExecutionStage:
        """Get a stage by name."""
        if name not in self._plugins:
            raise PluginNotFound(f"Execution stage '{name}' not found")
        if not self._enabled.get(name, False):
            raise PluginNotFound(f"Execution stage '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise PluginNotFound(f"Execution stage '{name}' is unhealthy")
        return self._plugins[name]

    def _generate_idempotency_key(self, decision: dict, context: dict) -> str:
        """Generate a deterministic key for this trade to prevent duplicates."""
        parts = [
            str(decision.get("token_id", "")),
            str(decision.get("market_ticker", "")),
            str(decision.get("direction", "")),
            str(decision.get("size", "")),
            str(context.get("strategy_name", "")),
            str(context.get("mode", "")),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def run_pipeline(self, decision: dict, context: dict) -> dict:
        """Run all registered stages in order.

        Args:
            decision: Trade decision dict
            context: Execution context dict with mode, bankroll, etc.

        Returns:
            Combined results dict from all stages
        """
        idempotency_key = self._generate_idempotency_key(decision, context)
        context["_idempotency_key"] = idempotency_key
        context["_pipeline_start_time"] = time.monotonic()

        results = {"idempotency_key": idempotency_key}
        stages = self._get_stages_by_order()
        for stage in stages:
            if stage.validate(decision, context):
                result = stage.execute(decision, context)
                stage.record(decision, result, context)
                results.update(result)
                if result.get("status") in ("error", "rejected"):
                    break
            else:
                results["validation_failed"] = True
                break
        return results

    def run_mode(self, mode: str, decision: dict, context: dict) -> dict:
        """Run stages filtered by mode.

        Args:
            mode: Trading mode ("paper", "testnet", "live")
            decision: Trade decision dict
            context: Execution context dict

        Returns:
            Combined results dict from matching stages
        """
        results = {}
        for name, stage in self._plugins.items():
            manifest = self._manifests[name]
            if manifest.mode == "*" or manifest.mode == mode:
                if stage.validate(decision, context):
                    result = stage.execute(decision, context)
                    stage.record(decision, result, context)
                    results.update(result)
                else:
                    results["validation_failed"] = True
                    break
        return results

    def _get_stages_by_order(self) -> List[BaseExecutionStage]:
        """Get all enabled stages sorted by manifest.order."""
        enabled = [
            (n, s) for n, s in self._plugins.items() if self._enabled.get(n, False)
        ]
        enabled.sort(key=lambda x: self._manifests[x[0]].order)
        return [s for _, s in enabled]

    def health_check(self) -> bool:
        for name, stage in self._plugins.items():
            if not stage.health_check():
                return False
        return True

    def register(self, plugin_class: type) -> None:
        manifest = plugin_class.manifest()
        name = manifest.name

        import os as _os
        from backend.core.plugin_errors import PluginEnvVarMissing

        if not settings.SHADOW_MODE and not _os.environ.get("SHADOW_MODE"):
            missing = [v for v in manifest.required_env_vars if not _os.environ.get(v)]
            if missing:
                raise PluginEnvVarMissing(
                    f"Execution stage '{name}' requires env vars: {missing}"
                )

        try:
            instance = plugin_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
        except Exception:
            logger.warning("Failed to load execution stage '%s'", name, exc_info=True)


registry = ExecutionPipelineRegistry()
