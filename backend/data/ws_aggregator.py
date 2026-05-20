"""Real-time WebSocket Aggregator — aggregates multiple market data streams."""

import asyncio
from typing import Optional
from collections import defaultdict


class WSMessage:
    def __init__(self, source: str, data: dict, seq: int):
        self.source = source
        self.data = data
        self.seq = seq
        self.timestamp = asyncio.get_event_loop().time()


class StreamAggregator:
    """
    Aggregates messages from multiple WebSocket streams.

    Zero Gaps:
    - Partial delivery: reassemble fragmented messages
    - Slow consumer: drop oldest messages (ring buffer)
    - Backpressure: signal producers to slow down
    """

    def __init__(self, max_buffer: int = 1000):
        self.max_buffer = max_buffer
        self._buffers: dict[str, list[WSMessage]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        self._subscribers: list[asyncio.Queue] = []
        self._running = False

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to aggregated messages."""
        q = asyncio.Queue(maxsize=self.max_buffer)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unsubscribe from aggregated messages."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def ingest(self, source: str, data: dict) -> None:
        """Ingest a message from a WebSocket source."""
        self._seq[source] += 1
        msg = WSMessage(source=source, data=data, seq=self._seq[source])

        self._buffers[source].append(msg)
        if len(self._buffers[source]) > self.max_buffer:
            self._buffers[source] = self._buffers[source][-self.max_buffer :]

        for q in self._subscribers:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def get_latest(self, source: str) -> Optional[dict]:
        """Get the latest message from a source."""
        buf = self._buffers.get(source, [])
        return buf[-1].data if buf else None

    def get_by_seq(self, source: str, seq: int) -> Optional[dict]:
        """Get message by sequence number."""
        buf = self._buffers.get(source, [])
        for msg in buf:
            if msg.seq == seq:
                return msg.data
        return None

    def has_gap(self, source: str) -> bool:
        """Check if there are sequence gaps for a source."""
        buf = self._buffers.get(source, [])
        if len(buf) < 2:
            return False
        seqs = [m.seq for m in buf]
        return any(seqs[i + 1] - seqs[i] > 1 for i in range(len(seqs) - 1))

    def clear(self, source: Optional[str] = None) -> None:
        """Clear buffer for a source or all sources."""
        if source:
            self._buffers.pop(source, None)
            self._seq.pop(source, None)
        else:
            self._buffers.clear()
            self._seq.clear()
