"""DataMesh — parallel, timeout-isolated data ingestion with provenance."""
from __future__ import annotations
import asyncio
import time
from typing import Dict, List, Optional

from backend.mesh.base import DataQuery, RawPacket, Provenance
from backend.mesh.registry import get, is_quarantined

from loguru import logger


class DataMesh:
    def __init__(self, default_timeout_ms: int = 5000):
        self.default_timeout_ms = default_timeout_ms

    async def ingest(self, source_id: str, query: DataQuery) -> Optional[RawPacket]:
        source = get(source_id)
        if not source or is_quarantined(source_id):
            return None
        try:
            t0 = time.monotonic()
            packet = await asyncio.wait_for(source.ingest(query), timeout=self.default_timeout_ms / 1000)
            packet.latency_ms = (time.monotonic() - t0) * 1000
            return packet
        except asyncio.TimeoutError:
            logger.warning(f"DataMesh: source '{source_id}' timed out ({self.default_timeout_ms}ms)")
            return RawPacket(source_id=source_id, data=None, provenance=Provenance(
                source_id=source_id, raw_data_hash="timeout",
                ingestion_timestamp=None, schema_version="?", confidence=0.0),
                error="timeout")
        except Exception as e:
            logger.error(f"DataMesh: source '{source_id}' failed: {e}")
            return RawPacket(source_id=source_id, data=None, provenance=Provenance(
                source_id=source_id, raw_data_hash="error",
                ingestion_timestamp=None, schema_version="?", confidence=0.0),
                error=str(e))

    async def ingest_parallel(self, queries: Dict[str, DataQuery]) -> Dict[str, RawPacket]:
        tasks = {sid: asyncio.create_task(self.ingest(sid, q)) for sid, q in queries.items()}
        results = {}
        for sid, task in tasks.items():
            try:
                packet = await task
                if packet:
                    results[sid] = packet
            except Exception as e:
                logger.error(f"DataMesh: unhandled ingest error for '{sid}': {e}")
        return results

    async def ingest_best_effort(self, source_ids: List[str], query_template: DataQuery) -> List[RawPacket]:
        queries = {sid: DataQuery(source_id=sid, market=query_template.market,
                                   ticker=query_template.ticker, limit=query_template.limit,
                                   extra=query_template.extra) for sid in source_ids}
        results = await self.ingest_parallel(queries)
        return [p for p in results.values() if p and p.data is not None]

    def cross_validate(self, packets: List[RawPacket]) -> float:
        valid = [p for p in packets if p.data is not None and not p.error]
        if len(valid) >= 2:
            return 1.0 + min(0.3, (len(valid) - 1) * 0.1)
        if len(valid) == 1:
            return 0.8
        return 0.3
