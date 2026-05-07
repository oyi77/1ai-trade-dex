"""CLOB Event Indexer — indexes OrderFilled events from Polymarket CLOB contract on Polygon."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("trading_bot.clob_event_indexer")

CLOB_CONTRACT = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
DEFAULT_BLOCK_CHUNK = 10000


class CLOBEventIndexer:
    """Index OrderFilled events from Polymarket CLOB contract.

    Requires web3 library. Falls back gracefully if not installed.
    """

    def __init__(self, rpc_url: Optional[str] = None, contract: Optional[str] = None):
        self.rpc_url = rpc_url or "https://polygon-rpc.com"
        self.contract = contract or CLOB_CONTRACT
        self._w3 = None
        self._last_indexed_block: int = 0

    def _get_w3(self):
        if self._w3 is None:
            try:
                from web3 import Web3
                self._w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            except ImportError:
                raise ImportError("web3 library required: pip install web3")
        return self._w3

    def fetch_events(self, from_block: int, to_block: Optional[int] = None) -> list[dict]:
        w3 = self._get_w3()
        if to_block is None:
            to_block = w3.eth.block_number

        events = []
        for start in range(from_block, to_block + 1, DEFAULT_BLOCK_CHUNK):
            end = min(start + DEFAULT_BLOCK_CHUNK - 1, to_block)
            try:
                logs = w3.eth.get_logs({
                    "address": self.contract,
                    "topics": [ORDER_FILLED_TOPIC],
                    "fromBlock": start,
                    "toBlock": end,
                })
                for log in logs:
                    events.append(self._decode_event(log))
            except Exception as e:
                logger.warning(f"CLOB event fetch failed blocks {start}-{end}: {e}")

        self._last_indexed_block = to_block
        return events

    def _decode_event(self, log) -> dict:
        return {
            "transaction_hash": log.transactionHash.hex() if log.transactionHash else "",
            "block_number": log.blockNumber,
            "address": log.address,
            "topics": [t.hex() if t else "" for t in log.topics],
            "data": log.data.hex() if log.data else "",
            "log_index": log.logIndex,
        }

    @property
    def last_indexed_block(self) -> int:
        return self._last_indexed_block

    @last_indexed_block.setter
    def last_indexed_block(self, value: int):
        self._last_indexed_block = value
