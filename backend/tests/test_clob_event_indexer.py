"""Tests for backend/data/clob_event_indexer.py."""

from unittest.mock import MagicMock, patch
import pytest

# Try importing HexBytes, fallback to mock/bytes if not installed in env.
try:
    from hexbytes import HexBytes
except ImportError:
    HexBytes = lambda x: x if isinstance(x, bytes) else bytes.fromhex(x.replace("0x", ""))

from backend.data.clob_event_indexer import CLOBEventIndexer, ORDER_FILLED_TOPIC
from backend.data.goldsky_client import process_trade_event


class MockLog:
    """Helper mock object representing a raw EVM log."""
    def __init__(self, topics, data, block_number, log_index, transaction_hash):
        self.topics = topics
        self.data = data
        self.blockNumber = block_number
        self.logIndex = log_index
        self.transactionHash = transaction_hash


def _create_order_filled_data(
    maker_asset_id: int,
    maker_amount: int,
    taker_asset_id: int,
    taker_amount: int
) -> bytes:
    """Helper to generate ABI encoded 128-byte unindexed data for OrderFilled."""
    m_asset = maker_asset_id.to_bytes(32, byteorder="big")
    m_amount = maker_amount.to_bytes(32, byteorder="big")
    t_asset = taker_asset_id.to_bytes(32, byteorder="big")
    t_amount = taker_amount.to_bytes(32, byteorder="big")
    return m_asset + m_amount + t_asset + t_amount


def test_decode_event_success():
    """Verify that a valid raw OrderFilled log is parsed into a Goldsky-compatible dict."""
    maker_topic = HexBytes("0x0000000000000000000000001111111111111111111111111111111111111111")
    taker_topic = HexBytes("0x0000000000000000000000002222222222222222222222222222222222222222")
    topics = [HexBytes(ORDER_FILLED_TOPIC), maker_topic, taker_topic]

    data_bytes = _create_order_filled_data(
        maker_asset_id=0,
        maker_amount=50_000_000,   # 50 USDC (6 decimals)
        taker_asset_id=98765,
        taker_amount=100_000_000   # 100 tokens
    )

    log = MockLog(
        topics=topics,
        data=data_bytes,
        block_number=12345,
        log_index=3,
        transaction_hash=HexBytes("0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
    )

    indexer = CLOBEventIndexer(rpc_url="http://mock-rpc")
    mock_w3 = MagicMock()
    mock_w3.eth.get_block.return_value = MagicMock(timestamp=1716768000)
    indexer._w3 = mock_w3

    decoded = indexer._decode_event(log)

    assert decoded["id"] == "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890-3"
    assert decoded["maker"] == "0x1111111111111111111111111111111111111111"
    assert decoded["taker"] == "0x2222222222222222222222222222222222222222"
    assert decoded["makerAssetId"] == "0"
    assert decoded["makerAmountFilled"] == "50000000"
    assert decoded["takerAssetId"] == "98765"
    assert decoded["takerAmountFilled"] == "100000000"
    assert decoded["timestamp"] == 1716768000
    assert decoded["transactionHash"] == "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

    # Verify get_block called once
    mock_w3.eth.get_block.assert_called_once_with(12345)


def test_block_timestamp_cache_efficiency():
    """Verify that multiple logs in the same block retrieve the block header only once."""
    maker_topic = HexBytes("0x0000000000000000000000001111111111111111111111111111111111111111")
    taker_topic = HexBytes("0x0000000000000000000000002222222222222222222222222222222222222222")
    topics = [HexBytes(ORDER_FILLED_TOPIC), maker_topic, taker_topic]
    data_bytes = _create_order_filled_data(0, 10, 98765, 20)

    log1 = MockLog(topics, data_bytes, 100, 1, HexBytes("0xa1"))
    log2 = MockLog(topics, data_bytes, 100, 2, HexBytes("0xa2"))

    indexer = CLOBEventIndexer(rpc_url="http://mock-rpc")
    mock_w3 = MagicMock()
    mock_w3.eth.get_block.return_value = MagicMock(timestamp=999999)
    indexer._w3 = mock_w3

    # First decode
    dec1 = indexer._decode_event(log1)
    # Second decode
    dec2 = indexer._decode_event(log2)

    assert dec1["timestamp"] == 999999
    assert dec2["timestamp"] == 999999
    # Assert get_block is called exactly once
    mock_w3.eth.get_block.assert_called_once_with(100)


def test_decode_event_invalid_inputs():
    """Verify that decoding raises appropriate errors when topics or data length is invalid."""
    indexer = CLOBEventIndexer(rpc_url="http://mock-rpc")
    indexer._w3 = MagicMock()

    # Invalid topics
    log_short_topics = MockLog(
        topics=[HexBytes(ORDER_FILLED_TOPIC)],
        data=b"\x00" * 128,
        block_number=10,
        log_index=1,
        transaction_hash=HexBytes("0x12")
    )
    with pytest.raises(ValueError, match="Invalid topics length"):
        indexer._decode_event(log_short_topics)

    # Invalid data length
    log_short_data = MockLog(
        topics=[
            HexBytes(ORDER_FILLED_TOPIC),
            HexBytes("0x0000000000000000000000001111111111111111111111111111111111111111"),
            HexBytes("0x0000000000000000000000002222222222222222222222222222222222222222")
        ],
        data=b"\x00" * 100, # less than 128 bytes
        block_number=10,
        log_index=1,
        transaction_hash=HexBytes("0x12")
    )
    with pytest.raises(ValueError, match="Invalid data length"):
        indexer._decode_event(log_short_data)


def test_fetch_events_integration():
    """Verify fetch_events loops, calls RPC get_logs, and updates indexer block checkpoint."""
    indexer = CLOBEventIndexer(rpc_url="http://mock-rpc")
    mock_w3 = MagicMock()
    mock_w3.eth.block_number = 5000
    
    # Setup mock logs
    maker_topic = HexBytes("0x0000000000000000000000001111111111111111111111111111111111111111")
    taker_topic = HexBytes("0x0000000000000000000000002222222222222222222222222222222222222222")
    topics = [HexBytes(ORDER_FILLED_TOPIC), maker_topic, taker_topic]
    data_bytes = _create_order_filled_data(0, 50_000_000, 999, 100_000_000)

    log = MockLog(
        topics=topics,
        data=data_bytes,
        block_number=4500,
        log_index=1,
        transaction_hash=HexBytes("0xabc")
    )

    mock_w3.eth.get_logs.return_value = [log]
    mock_w3.eth.get_block.return_value = MagicMock(timestamp=1716768000)
    indexer._w3 = mock_w3

    events = indexer.fetch_events(from_block=4000, to_block=5000)

    assert len(events) == 1
    assert events[0]["maker"] == "0x1111111111111111111111111111111111111111"
    assert indexer.last_indexed_block == 5000
    mock_w3.eth.get_logs.assert_called()


def test_integration_with_goldsky_normalization():
    """Verify that decoded dict format can be parsed by goldsky_client.process_trade_event."""
    maker_topic = HexBytes("0x0000000000000000000000001111111111111111111111111111111111111111")
    taker_topic = HexBytes("0x0000000000000000000000002222222222222222222222222222222222222222")
    topics = [HexBytes(ORDER_FILLED_TOPIC), maker_topic, taker_topic]
    data_bytes = _create_order_filled_data(
        maker_asset_id=0,          # USDC side
        maker_amount=15_000_000,   # 15 USDC
        taker_asset_id=98765,      # Token side
        taker_amount=30_000_000    # 30 tokens
    )

    log = MockLog(
        topics=topics,
        data=data_bytes,
        block_number=1000,
        log_index=5,
        transaction_hash=HexBytes("0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
    )

    indexer = CLOBEventIndexer(rpc_url="http://mock-rpc")
    mock_w3 = MagicMock()
    mock_w3.eth.get_block.return_value = MagicMock(timestamp=1700000000)
    indexer._w3 = mock_w3

    # Decode using the indexer
    decoded_event = indexer._decode_event(log)

    # Process using goldsky normalization
    normalized = process_trade_event(decoded_event)

    assert normalized is not None
    assert normalized["maker"] == "0x1111111111111111111111111111111111111111"
    assert normalized["taker"] == "0x2222222222222222222222222222222222222222"
    assert normalized["market_token_id"] == "98765"
    assert normalized["maker_direction"] == "BUY"
    assert normalized["taker_direction"] == "SELL"
    assert normalized["usd_amount"] == pytest.approx(15.0)
    assert normalized["token_amount"] == pytest.approx(30.0)
    assert normalized["price"] == pytest.approx(0.5)
    assert normalized["tx_hash"] == "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    assert normalized["timestamp"] == 1700000000
