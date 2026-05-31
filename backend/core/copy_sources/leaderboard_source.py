from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.core.copy_source import CopyPolicyConfig, CopySignalData, CopySource
from backend.models.database import WalletConfig


class LeaderboardCopySource(CopySource):
    def __init__(self, db_session: Session, policy: CopyPolicyConfig | None) -> None:
        self._db = db_session
        self._policy = policy

    def get_name(self) -> str:
        return "leaderboard"

    async def fetch_signals(self) -> list[CopySignalData]:
        max_delay = self._policy.max_delay_seconds if self._policy else 30
        now = datetime.now(timezone.utc)

        try:
            client = get_shared_client()
            resp = await client.get(
                f"{settings.DATA_API_URL}/data-api/v2/activity",
                params={"limit": 50},
            )
            resp.raise_for_status()
            activity = resp.json()
        except Exception as exc:
            logger.warning("leaderboard fetch failed: {}", exc)
            return []

        tracked: dict[str, float] = {}
        if self._db is not None:
            rows = (
                self._db.query(WalletConfig)
                .filter(
                    WalletConfig.source == "leaderboard", WalletConfig.enabled.is_(True)
                )
                .all()
            )
            tracked = {r.wallet_address: (r.whale_score or 50.0) for r in rows}

        signals: list[CopySignalData] = []
        for event in (
            activity if isinstance(activity, list) else activity.get("data", [])
        ):
            wallet_addr = event.get("maker_address") or event.get("wallet", "")
            if wallet_addr not in tracked:
                continue

            ts_raw = event.get("timestamp") or event.get("created_at", "")
            try:
                ts = datetime.fromisoformat(ts_raw.rstrip("Z")).replace(
                    tzinfo=timezone.utc
                )
            except Exception:
                continue

            age_seconds = (now - ts).total_seconds()
            if age_seconds > max_delay:
                continue

            signals.append(
                CopySignalData(
                    source_name=self.get_name(),
                    leader_address=wallet_addr,
                    condition_id=event.get("condition_id", ""),
                    side=event.get("side", "YES"),
                    raw_size=float(event.get("size", 0)),
                    confidence=tracked[wallet_addr] / 100.0,
                    captured_at=ts,
                    metadata={"event": event},
                )
            )

        return signals

    async def is_healthy(self) -> bool:
        try:
            client = get_shared_client()
            resp = await client.get(
                f"{settings.DATA_API_URL}/data-api/v2/activity", params={"limit": 1}
            )
            return resp.status_code == 200
        except Exception:
            return False
