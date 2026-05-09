import pytest
from unittest.mock import AsyncMock, patch

from backend.data.kalshi_client import KalshiClient


@pytest.fixture
def client():
    return KalshiClient()


class TestKalshiBatch:
    @pytest.mark.asyncio
    async def test_batch_create_orders(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"batch_id": "123"}
            orders = [{"ticker": "KXBTCUP", "side": "yes", "price": 65, "size": 10}]
            result = await client.batch_create_orders(orders)
            mock_req.assert_called_once_with(
                "POST", "/portfolio/batch_create_orders",
                json={"orders": orders}
            )
            assert result["batch_id"] == "123"

    @pytest.mark.asyncio
    async def test_batch_cancel_orders(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"cancelled": 2}
            ids = ["order-1", "order-2"]
            result = await client.batch_cancel_orders(ids)
            mock_req.assert_called_once_with(
                "DELETE", "/portfolio/batch_cancel_orders",
                json={"order_ids": ids}
            )
            assert result["cancelled"] == 2

    @pytest.mark.asyncio
    async def test_amend_order_price_only(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"amended": True}
            result = await client.amend_order("order-1", new_price=70.0)
            mock_req.assert_called_once_with(
                "POST", "/portfolio/amend_order",
                json={"order_id": "order-1", "new_price": 70.0}
            )
            assert result["amended"] is True

    @pytest.mark.asyncio
    async def test_amend_order_size_and_price(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"amended": True}
            await client.amend_order("order-2", new_price=55.0, new_size=20)
            mock_req.assert_called_once_with(
                "POST", "/portfolio/amend_order",
                json={"order_id": "order-2", "new_price": 55.0, "new_size": 20}
            )
