from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from backend.core.copy_source import CopyPolicyConfig, CopySignalData
from backend.models.trading_wallet import CopyPolicy


class CopyPolicyEngine:
    def __init__(self, db_session: Session, sandbox_manager=None) -> None:
        self._db = db_session
        self._sandbox = sandbox_manager
        self._policy_cache: dict[str, CopyPolicyConfig] = {}
        self._cooldown_tracker: dict[str, datetime] = {}
        self._refreshed_at: datetime | None = None

    def _refresh_cache(self) -> None:
        if self._db is None:
            return
        rows = self._db.query(CopyPolicy).all()
        self._policy_cache = {
            r.source_name: CopyPolicyConfig(
                source_name=r.source_name,
                enabled=r.enabled,
                max_size_usd=r.max_size_usd,
                confidence_floor=r.confidence_floor,
                max_delay_seconds=r.max_delay_seconds,
                size_scale_factor=r.size_scale_factor,
                cooldown_seconds=r.cooldown_seconds,
            )
            for r in rows
        }
        self._refreshed_at = datetime.now(timezone.utc)

    def _get_policy(self, source_name: str) -> CopyPolicyConfig | None:
        if not self._policy_cache:
            self._refresh_cache()
        return self._policy_cache.get(source_name)

    async def process(
        self, signals: list[CopySignalData], source_name: str
    ) -> list[CopySignalData]:
        policy = self._get_policy(source_name)
        if policy is None:
            logger.warning("no CopyPolicy row for source={} — all signals dropped", source_name)
            return []

        if not policy.enabled:
            return []

        now = datetime.now(timezone.utc)
        accepted: list[CopySignalData] = []

        for sig in signals:
            if sig.confidence < policy.confidence_floor:
                continue

            age = (now - sig.captured_at).total_seconds()
            if age > policy.max_delay_seconds:
                continue

            cooldown_key = f"{source_name}:{sig.leader_address}"
            last = self._cooldown_tracker.get(cooldown_key)
            if last is not None and (now - last).total_seconds() < policy.cooldown_seconds:
                continue

            scaled = sig.raw_size * policy.size_scale_factor
            final_size = min(scaled, policy.max_size_usd)

            if self._sandbox is not None:
                sandbox_result = await self._sandbox.validate_strategy(
                    f"# copy signal from {source_name}", "copy_signal"
                )
                if sandbox_result.status != "passed":
                    logger.warning("sandbox rejected copy signal from source={}", source_name)
                    continue

            self._cooldown_tracker[cooldown_key] = now
            from dataclasses import replace
            accepted.append(replace(sig, raw_size=final_size))

        return accepted

    async def update_policy(self, source_name: str, updates: dict) -> CopyPolicy:
        if self._db is None:
            raise RuntimeError("db_session required for update_policy")
        row = self._db.query(CopyPolicy).filter(CopyPolicy.source_name == source_name).first()
        if row is None:
            row = CopyPolicy(source_name=source_name, **updates)
            self._db.add(row)
        else:
            for k, v in updates.items():
                setattr(row, k, v)
        self._db.commit()
        self._refresh_cache()
        return row
