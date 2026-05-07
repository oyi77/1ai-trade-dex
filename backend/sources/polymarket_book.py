"""PolymarketBook DataSource — live order book, Gamma API markets, and whale positions."""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from backend.mesh.base import DataSource, DataQuery, RawPacket, Provenance, HealthStatus, SourceState
from backend.config import settings

logger = logging.getLogger("trading_bot.sources.polymarket_book")

GAMMA_URL = settings.GAMMA_API_URL


class PolymarketBook(DataSource):
    source_id = "polymarket_book"
    schema_version = "1.0.0"

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._success_count = 0
        self._fail_count = 0
        self._latencies: list[float] = []

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def ingest(self, query: DataQuery) -> RawPacket:
        t0 = time.monotonic()
        client = await self._get_client()
        try:
            params = {"limit": query.limit or 20, "active": "true", "closed": "false",
                       "order": "volume", "ascending": "false"}
            if query.ticker:
                resp = await client.get(f"{GAMMA_URL}/markets/{query.ticker}")
            else:
                resp = await client.get(f"{GAMMA_URL}/markets", params=params)
            resp.raise_for_status()
            raw_text = resp.text
            self._success_count += 1
            return RawPacket(
                source_id=self.source_id,
                data=resp.json(),
                provenance=Provenance.from_raw(self.source_id, raw_text, self.schema_version, 0.95),
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as e:
            self._fail_count += 1
            logger.debug(f"PolymarketBook ingest failed: {e}")
            return RawPacket(
                source_id=self.source_id,
                data=None,
                provenance=Provenance.from_raw(self.source_id, str(e), self.schema_version, 0.0),
                latency_ms=(time.monotonic() - t0) * 1000,
                error=str(e),
            )

    async def health_check(self) -> HealthStatus:
        _t0 = time.monotonic()
        try:
            client = await self._get_client()
            resp = await asyncio.wait_for(client.get(f"{GAMMA_URL}/markets?limit=1"), timeout=5.0)
            ok = resp.status_code == 200
        except Exception:
            ok = False
        total = max(self._success_count + self._fail_count, 1)
        return HealthStatus(
            source_id=self.source_id,
            state=SourceState.HEALTHY if ok else SourceState.DEGRADED,
            success_rate=self._success_count / total,
            p95_latency_ms=sorted(self._latencies)[int(len(self._latencies) * 0.95)] if len(self._latencies) >= 20 else 200,
            staleness_seconds=0.0,
            consecutive_failures=0 if ok else 1,
            last_check=datetime.now(timezone.utc),
        )
