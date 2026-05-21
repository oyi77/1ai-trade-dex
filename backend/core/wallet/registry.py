"""Module-level registry for shared wallet/copy components.

Lifespan populates these singletons at startup; orchestrator and
scheduling strategies read them when constructing AutoTrader.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.copy_engine import CopyPolicyEngine
    from backend.core.wallet_router import WalletRouter

_wallet_router: WalletRouter | None = None
_copy_engine: CopyPolicyEngine | None = None


def set_wallet_router(router: WalletRouter | None) -> None:
    global _wallet_router
    _wallet_router = router


def get_wallet_router() -> WalletRouter | None:
    return _wallet_router


def set_copy_engine(engine: CopyPolicyEngine | None) -> None:
    global _copy_engine
    _copy_engine = engine


def get_copy_engine() -> CopyPolicyEngine | None:
    return _copy_engine
