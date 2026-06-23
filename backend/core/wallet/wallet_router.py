"""DEPRECATED: Use backend.core.wallet_router instead.

DEPRECATED: Use backend.core.wallet_router instead.
This module will be removed in a future release.


This module will be removed in a future release.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.fernet import Fernet
from loguru import logger
from sqlalchemy.orm import Session

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.risk.risk_manager import IMMUTABLE_SAFETY_RULES
from backend.models.trading_wallet import TradingWallet, WalletAllocation

MIN_ORDER_SIZE: dict[str, float] = {
    "polymarket": 1.0,
    "kalshi": 0.01,
}


@dataclass
class ChildOrder:
    wallet_id: int
    wallet_address: str
    chain: str
    size: float
    condition_id: str
    side: str
    decrypted_key: str


class WalletRouter:
    def __init__(self, db_session: Session, fernet_key: bytes) -> None:
        self._db = db_session
        self._fernet = Fernet(fernet_key)
        self._breakers: dict[int, CircuitBreaker] = {}

    def _breaker_for(self, wallet_id: int) -> CircuitBreaker:
        if wallet_id not in self._breakers:
            self._breakers[wallet_id] = CircuitBreaker(
                f"wallet_{wallet_id}", failure_threshold=3, recovery_timeout=120.0
            )
        return self._breakers[wallet_id]

    def decrypt_key(self, encrypted: str) -> str:
        return self._fernet.decrypt(encrypted.encode()).decode()

    async def get_wallets_for_strategy(
        self, strategy_name: str
    ) -> list[WalletAllocation]:
        rows = (
            self._db.query(WalletAllocation)
            .filter(
                WalletAllocation.strategy_name == strategy_name,
                WalletAllocation.enabled.is_(True),
            )
            .order_by(WalletAllocation.weight.desc())
            .all()
        )
        return rows

    async def fan_out(
        self,
        signal_size: float,
        condition_id: str,
        side: str,
        strategy_name: str,
        bankroll: float,
    ) -> list[ChildOrder]:
        allocations = await self.get_wallets_for_strategy(strategy_name)
        if not allocations:
            return []

        max_exposure_fraction = float(
            os.environ.get(
                IMMUTABLE_SAFETY_RULES["max_total_exposure"]["override_env_var"],
                IMMUTABLE_SAFETY_RULES["max_total_exposure"]["default"],
            )
        )
        max_total_exposure = bankroll * max_exposure_fraction

        child_orders: list[ChildOrder] = []
        for alloc in allocations:
            child_size = signal_size * alloc.weight
            if alloc.max_exposure_usd is not None:
                child_size = min(child_size, alloc.max_exposure_usd)

            wallet: TradingWallet | None = (
                self._db.query(TradingWallet)
                .filter(
                    TradingWallet.id == alloc.wallet_id, TradingWallet.enabled.is_(True)
                )
                .first()
            )
            if wallet is None:
                logger.warning(
                    "wallet_id={} not found or disabled — skipping child order",
                    alloc.wallet_id,
                )
                continue

            min_size = MIN_ORDER_SIZE.get(wallet.chain, 1.0)
            if child_size < min_size:
                logger.warning(
                    "child_size={:.4f} below MIN_ORDER_SIZE={} for chain={} wallet_id={} — skipping",
                    child_size,
                    min_size,
                    wallet.chain,
                    wallet.id,
                )
                continue

            if child_size > max_total_exposure:
                logger.warning(
                    "child_size={:.2f} exceeds max_total_exposure={:.2f} — capping",
                    child_size,
                    max_total_exposure,
                )
                child_size = max_total_exposure

            breaker = self._breaker_for(wallet.id)
            if breaker.state != "CLOSED":
                logger.warning(
                    "circuit open for wallet_id={} — skipping child order", wallet.id
                )
                continue

            raw_key = ""
            if wallet.encrypted_private_key:
                raw_key = self.decrypt_key(wallet.encrypted_private_key)

            child_orders.append(
                ChildOrder(
                    wallet_id=wallet.id,
                    wallet_address=wallet.address,
                    chain=wallet.chain,
                    size=child_size,
                    condition_id=condition_id,
                    side=side,
                    decrypted_key=raw_key,
                )
            )

        return child_orders
