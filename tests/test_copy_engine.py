import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models.database import Base
from backend.models.trading_wallet import CopyPolicy
from backend.core.copy_engine import CopyPolicyEngine
from backend.core.copy_source import CopySignalData
from datetime import datetime, timezone

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.mark.asyncio
async def test_copy_engine_filter_disabled(db_session):
    policy = CopyPolicy(
        source_name="test_src",
        enabled=False
    )
    db_session.add(policy)
    db_session.commit()
    
    engine = CopyPolicyEngine(db_session)
    signal = CopySignalData(
        source_name="test_src",
        leader_address="0x123",
        condition_id="0xabc",
        side="YES",
        raw_size=100.0,
        confidence=0.8,
        captured_at=datetime.now(timezone.utc)
    )
    
    processed = await engine.process([signal], "test_src")
    assert len(processed) == 0

@pytest.mark.asyncio
async def test_copy_engine_scale_and_confidence(db_session):
    policy = CopyPolicy(
        source_name="test_src",
        enabled=True,
        size_scale_factor=0.5,
        confidence_floor=0.9
    )
    db_session.add(policy)
    db_session.commit()
    
    engine = CopyPolicyEngine(db_session)
    signal1 = CopySignalData(
        source_name="test_src",
        leader_address="0x123",
        condition_id="0xabc",
        side="YES",
        raw_size=100.0,
        confidence=0.8,
        captured_at=datetime.now(timezone.utc)
    )
    assert len(await engine.process([signal1], "test_src")) == 0
    
    signal2 = CopySignalData(
        source_name="test_src",
        leader_address="0x123",
        condition_id="0xabc",
        side="YES",
        raw_size=100.0,
        confidence=0.95,
        captured_at=datetime.now(timezone.utc)
    )
    processed = await engine.process([signal2], "test_src")
    assert len(processed) == 1
    assert processed[0].raw_size == 50.0
