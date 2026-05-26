"""CLOB Event Indexer — indexes OrderFilled events from Polymarket CLOB contract on Polygon."""

from __future__ import annotations

from typing import Optional
from loguru import logger
from backend.config import settings

CLOB_CONTRACT = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
ORDER_FILLED_TOPIC = (
    "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
)
DEFAULT_BLOCK_CHUNK = 10000


class CLOBEventIndexer:
    """Index OrderFilled events from Polymarket CLOB contract.

    Requires web3 library. Falls back gracefully if not installed.
    """

    def __init__(self, rpc_url: Optional[str] = None, contract: Optional[str] = None):
        self.rpc_url = rpc_url or settings.POLYGON_RPC_URL
        self.contract = contract or CLOB_CONTRACT
        self._w3 = None
        self._last_indexed_block: int = 0
        self._block_time_cache: dict[int, int] = {}

    def _get_w3(self):
        if self._w3 is None:
            try:
                from web3 import Web3

                self._w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            except ImportError:
                raise ImportError("web3 library required: pip install web3")
        return self._w3

    def fetch_events(
        self, from_block: int, to_block: Optional[int] = None
    ) -> list[dict]:
        w3 = self._get_w3()
        if to_block is None:
            to_block = w3.eth.block_number

        events = []
        for start in range(from_block, to_block + 1, DEFAULT_BLOCK_CHUNK):
            end = min(start + DEFAULT_BLOCK_CHUNK - 1, to_block)
            try:
                logs = w3.eth.get_logs(
                    {
                        "address": self.contract,
                        "topics": [ORDER_FILLED_TOPIC],
                        "fromBlock": start,
                        "toBlock": end,
                    }
                )
                for log in logs:
                    try:
                        decoded = self._decode_event(log)
                        events.append(decoded)
                    except Exception as e:
                        logger.error(f"Failed to decode log: {e}")
            except Exception as e:
                logger.warning(f"CLOB event fetch failed blocks {start}-{end}: {e}")

        self._last_indexed_block = to_block
        return events

    def _decode_event(self, log) -> dict:
        def _get_val(obj, key):
            try:
                return getattr(obj, key)
            except AttributeError:
                try:
                    return obj[key]
                except (KeyError, TypeError):
                    return None

        tx_hash_val = _get_val(log, "transactionHash")
        tx_hash = ""
        if tx_hash_val:
            if isinstance(tx_hash_val, bytes):
                tx_hash = tx_hash_val.hex()
            else:
                tx_hash = str(tx_hash_val)
                if tx_hash.startswith("0x"):
                    tx_hash = tx_hash[2:]
        tx_hash = "0x" + tx_hash

        block_number = _get_val(log, "blockNumber") or 0
        log_index = _get_val(log, "logIndex") or 0

        topics = _get_val(log, "topics") or []
        if len(topics) < 3:
            raise ValueError(f"Invalid topics length: {len(topics)}, expected >= 3")

        def _parse_address(topic) -> str:
            if isinstance(topic, str):
                addr_hex = topic
            elif isinstance(topic, bytes):
                addr_hex = topic.hex()
            else:
                addr_hex = str(topic)
            if addr_hex.startswith("0x"):
                addr_hex = addr_hex[2:]
            return "0x" + addr_hex[-40:].lower()

        maker_address = _parse_address(topics[1])
        taker_address = _parse_address(topics[2])

        data_val = _get_val(log, "data") or b""
        if isinstance(data_val, str):
            if data_val.startswith("0x"):
                data_val = data_val[2:]
            data_bytes = bytes.fromhex(data_val)
        else:
            data_bytes = bytes(data_val)

        if len(data_bytes) < 128:
            raise ValueError(f"Invalid data length: {len(data_bytes)}, expected >= 128 bytes")

        maker_asset_id = int.from_bytes(data_bytes[0:32], byteorder="big")
        maker_amount_filled = int.from_bytes(data_bytes[32:64], byteorder="big")
        taker_asset_id = int.from_bytes(data_bytes[64:96], byteorder="big")
        taker_amount_filled = int.from_bytes(data_bytes[96:128], byteorder="big")

        if block_number in self._block_time_cache:
            timestamp = self._block_time_cache[block_number]
        else:
            w3 = self._get_w3()
            try:
                block = w3.eth.get_block(block_number)
                timestamp = block.timestamp
            except Exception as e:
                logger.warning(f"Could not fetch timestamp for block {block_number}: {e}")
                timestamp = 0

            if timestamp > 0:
                if len(self._block_time_cache) >= 10000:
                    first_key = next(iter(self._block_time_cache))
                    self._block_time_cache.pop(first_key)
                self._block_time_cache[block_number] = timestamp

        return {
            "id": f"{tx_hash}-{log_index}",
            "timestamp": timestamp,
            "maker": maker_address,
            "makerAssetId": str(maker_asset_id),
            "makerAmountFilled": str(maker_amount_filled),
            "taker": taker_address,
            "takerAssetId": str(taker_asset_id),
            "takerAmountFilled": str(taker_amount_filled),
            "transactionHash": tx_hash,
        }

    @property
    def last_indexed_block(self) -> int:
        return self._last_indexed_block

    @last_indexed_block.setter
    def last_indexed_block(self, value: int):
        self._last_indexed_block = value
