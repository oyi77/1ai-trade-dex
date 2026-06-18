"""EdgeRegistry — pluggable edge scanner registration and management.

Scanners auto-register via EdgeScannerABC.__init_subclass__.
The registry manages scanner lifecycle, health checks, and parallel detection.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Type

from loguru import logger

from backend.core.edge.edge_model import Edge, EdgeType


class EdgeScannerABC:
    """Abstract base class for APEX edge scanners.

    Subclass this, set `name` and `edge_type`, implement `detect()`,
    and the scanner will auto-register in EdgeRegistry.
    """

    name: str = ""
    edge_type: EdgeType = EdgeType.RESOLUTION_TIMING
    description: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name and cls.name not in _PENDING_SCANNERS:
            _PENDING_SCANNERS[cls.name] = cls

    async def detect(self, ctx: Any) -> List[Edge]:  # noqa: D401
        """Scan and return detected edges.

        Args:
            ctx: StrategyContext with db, clob, settings, logger, bankroll, etc.

        Returns:
            List of Edge objects for tradeable opportunities.
        """
        raise NotImplementedError

    # Backwards-compatible alias — some scanner impls use ``scan(ctx)``
    async def scan(self, ctx: Any) -> List[Edge]:  # noqa: D401
        return await self.detect(ctx)

    async def health_check(self) -> bool:
        """Return True if scanner is healthy and can detect edges."""
        return True


# Module-level pending registrations (populated by __init_subclass__)
_PENDING_SCANNERS: Dict[str, Type[EdgeScannerABC]] = {}


class EdgeRegistry:
    """Manages registered edge scanners and runs detection cycles."""

    def __init__(self) -> None:
        self._scanners: Dict[str, EdgeScannerABC] = {}
        self._enabled: Dict[str, bool] = {}

    def register(self, scanner: EdgeScannerABC) -> None:
        """Register a scanner instance."""
        self._scanners[scanner.name] = scanner
        self._enabled[scanner.name] = True
        logger.info(f"[APEX] Registered scanner: {scanner.name} ({scanner.edge_type.value})")

    def register_class(self, cls: Type[EdgeScannerABC]) -> None:
        """Register a scanner class by instantiating it."""
        instance = cls()
        self.register(instance)

    def enable(self, name: str) -> None:
        """Enable a registered scanner."""
        if name in self._scanners:
            self._enabled[name] = True

    def disable(self, name: str) -> None:
        """Disable a registered scanner."""
        if name in self._scanners:
            self._enabled[name] = False

    def get(self, name: str) -> Optional[EdgeScannerABC]:
        """Get a scanner by name."""
        return self._scanners.get(name)

    def list_scanners(self) -> List[str]:
        """List all registered scanner names."""
        return list(self._scanners.keys())

    def list_enabled(self) -> List[str]:
        """List enabled scanner names."""
        return [name for name, enabled in self._enabled.items() if enabled]

    async def run_all(self, markets: List[Dict[str, Any]], ctx: Any) -> List[Edge]:
        """Run all enabled scanners in parallel and collect edges.

        Args:
            markets: Market data list.
            ctx: StrategyContext.

        Returns:
            Deduplicated list of edges, sorted by edge_score descending.
        """
        enabled = [self._scanners[n] for n in self.list_enabled()]
        if not enabled:
            return []

        # Run all scanners concurrently
        tasks = [scanner.scan(ctx) for scanner in enabled]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_edges: List[Edge] = []
        for scanner, result in zip(enabled, results):
            if isinstance(result, Exception):
                logger.warning(f"[APEX] Scanner {scanner.name} failed: {result}")
                continue
            if result:
                all_edges.extend(result)

        # Deduplicate by (market_id, direction) — keep highest edge_score
        seen: Dict[tuple, Edge] = {}
        for edge in all_edges:
            key = (edge.market_id, edge.direction)
            if key not in seen or edge.edge_score > seen[key].edge_score:
                seen[key] = edge

        # Sort by edge_score descending
        deduped = sorted(seen.values(), key=lambda e: e.edge_score, reverse=True)
        return deduped

    def load_pending(self) -> None:
        """Load scanners that were registered via __init_subclass__."""
        for name, cls in _PENDING_SCANNERS.items():
            if name not in self._scanners:
                self.register_class(cls)
        _PENDING_SCANNERS.clear()

    async def health_check_all(self) -> Dict[str, bool]:
        """Run health checks on all enabled scanners."""
        results = {}
        for name in self.list_enabled():
            scanner = self._scanners[name]
            try:
                results[name] = await scanner.health_check()
            except Exception as e:
                logger.warning(f"[APEX] Health check failed for {name}: {e}")
                results[name] = False
        return results


# Global singleton
edge_registry = EdgeRegistry()


def auto_discover_scanners() -> None:
    """Import all scanner modules to trigger __init_subclass__ registration."""
    import importlib
    import pkgutil

    package = importlib.import_module("backend.core.edge.scanners")
    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if modname.startswith("_"):
            continue
        try:
            importlib.import_module(f"backend.core.edge.scanners.{modname}")
        except Exception as e:
            logger.warning(f"[APEX] Failed to import scanner module {modname}: {e}")

    # Load pending registrations
    edge_registry.load_pending()
