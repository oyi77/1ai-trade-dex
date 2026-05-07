import json
import pytest
from backend.data.polygon_listener import PolygonListener


@pytest.mark.asyncio
async def test_threshold_filter():
    got = []
    listener = PolygonListener(min_usd=500, on_whale=lambda d: _capture(got, d))

    # Patch _persist to avoid DB calls
    async def noop_persist(*args, **kwargs):
        pass
    listener._persist = noop_persist

    small = json.dumps({"params": {"result": {
        "transactionHash": "0xa", "blockNumber": "0x10",
        "topics": ["0xevt", "0x" + "0" * 24 + "1" * 40, "0x", "0xpos"],
        "data": hex(int(100 * 1e6))  # 100 USDC < 500 threshold
    }}})
    big = json.dumps({"params": {"result": {
        "transactionHash": "0xb", "blockNumber": "0x11",
        "topics": ["0xevt", "0x" + "0" * 24 + "2" * 40, "0x", "0xpos"],
        "data": hex(int(2000 * 1e6))  # 2000 USDC > 500
    }}})
    await listener._handle_message(small)
    await listener._handle_message(big)
    assert len(got) == 1
    assert got[0]["size_usd"] >= 500


async def _capture(buf, d):
    buf.append(d)
