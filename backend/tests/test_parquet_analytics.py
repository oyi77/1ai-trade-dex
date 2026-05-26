"""Unit tests for db_archiver and Parquet/DuckDB analytics integration."""

import os
import shutil
import tempfile
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.analytics import get_db
from backend.core.db_archiver import archive_trades_to_parquet, query_parquet_analytics
from backend.models.database import Trade


@pytest.fixture
def temp_dir():
    dir_path = tempfile.mkdtemp()
    yield dir_path
    shutil.rmtree(dir_path)


@pytest.fixture
def setup_test_db():
    db_path = tempfile.mktemp(suffix=".db")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.models.database import Base
    
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    
    with Session() as session:
        t1 = Trade(
            strategy="crypto_oracle",
            market_ticker="BTC-YES",
            direction="BUY",
            size=10.0,
            entry_price=0.25,
            settlement_value=1.0,
            pnl=7.5,
            result="win",
            role="maker",
            settled=True,
            timestamp=datetime.now(timezone.utc),
        )
        t2 = Trade(
            strategy="btc_oracle",
            market_ticker="BTC-NO",
            direction="SELL",
            size=20.0,
            entry_price=0.85,
            settlement_value=0.0,
            pnl=-20.0,
            result="loss",
            role="taker",
            settled=True,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(t1)
        session.add(t2)
        session.commit()
        
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


def test_archive_trades_to_parquet(setup_test_db, temp_dir):
    db_path = setup_test_db
    parquet_dir = os.path.join(temp_dir, "trades")
    
    count = archive_trades_to_parquet(db_path, parquet_dir, days_back=1)
    assert count == 2
    
    assert os.path.exists(parquet_dir)
    sql = "SELECT COUNT(*) as cnt, MAX(category) as cat FROM {table}"
    res = query_parquet_analytics(parquet_dir, sql)
    assert len(res) == 1
    assert res[0]["cnt"] == 2
    assert res[0]["cat"] == "btc"


def test_analytics_role_breakdown_endpoint(setup_test_db, temp_dir, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(f"sqlite:///{setup_test_db}")
    TestingSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    
    try:
        client = TestClient(app)
        
        from backend.config import settings
        monkeypatch.setattr(settings, "PARQUET_DIR", temp_dir)
        
        response = client.get("/api/v1/analytics/stats/role-breakdown?days=1")
        assert response.status_code == 200
        data = response.json()
        assert "roles" in data
        assert "maker" in data["roles"]
        assert "taker" in data["roles"]
        assert data["roles"]["maker"]["count"] == 1
        assert data["roles"]["taker"]["count"] == 1
        
        # 2. Test Parquet path
        parquet_dir = os.path.join(temp_dir, "trades")
        archive_trades_to_parquet(setup_test_db, parquet_dir, days_back=1)
        
        response = client.get("/api/v1/analytics/stats/role-breakdown?days=1")
        assert response.status_code == 200
        data = response.json()
        assert "roles" in data
        assert data["roles"]["maker"]["count"] == 1
        assert data["roles"]["maker"]["win_rate"] == 1.0
        assert data["roles"]["taker"]["count"] == 1
        assert data["roles"]["taker"]["win_rate"] == 0.0
    finally:
        app.dependency_overrides.clear()
