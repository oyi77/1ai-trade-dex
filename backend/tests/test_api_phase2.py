import pytest
from httpx import AsyncClient, ASGITransport
from backend.api.main import app
from backend.models.database import Base
from backend.tests.conftest import test_engine


@pytest.fixture(scope="session", autouse=True)
def ensure_phase2_tables():
    """Ensure WhaleTransaction and PendingApproval tables exist in the test DB."""
    Base.metadata.create_all(bind=test_engine)


@pytest.mark.asyncio
async def test_whale_transactions_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/whales/transactions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_arbitrage_opportunities():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/arbitrage/opportunities")
    assert r.status_code == 200
    assert "opportunities" in r.json()


@pytest.mark.asyncio
async def test_predictions_returns_503_when_data_unavailable():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/predictions/m1")
    assert r.status_code == 503
    body = r.json()
    assert "error" in body
    assert body["market_id"] == "m1"


@pytest.mark.asyncio
async def test_news_feed_handles_errors():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/news/feed")
    assert r.status_code == 200
