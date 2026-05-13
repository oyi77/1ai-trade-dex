import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models.database import Base
from backend.models.trading_wallet import TradingWallet, WalletAllocation
from backend.core.wallet_router import WalletRouter
from cryptography.fernet import Fernet

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def fernet_key():
    return Fernet.generate_key()

@pytest.fixture
def router(db_session, fernet_key):
    return WalletRouter(db_session, fernet_key)

@pytest.mark.asyncio
async def test_fan_out_no_allocations(router):
    orders = await router.fan_out(100.0, "cond_1", "BUY", "strat_1", 1000.0)
    assert orders == []

@pytest.mark.asyncio
async def test_fan_out_with_allocations(db_session, router, fernet_key):
    f = Fernet(fernet_key)
    enc_key = f.encrypt(b"secret").decode()
    
    w1 = TradingWallet(label="w1", address="0x1", chain="polymarket", enabled=True, encrypted_private_key=enc_key)
    w2 = TradingWallet(label="w2", address="0x2", chain="kalshi", enabled=True, encrypted_private_key=enc_key)
    db_session.add_all([w1, w2])
    db_session.commit()
    
    a1 = WalletAllocation(wallet_id=w1.id, strategy_name="strat_1", weight=0.6, enabled=True)
    a2 = WalletAllocation(wallet_id=w2.id, strategy_name="strat_1", weight=0.4, enabled=True)
    db_session.add_all([a1, a2])
    db_session.commit()
    
    orders = await router.fan_out(100.0, "cond_1", "BUY", "strat_1", 10000.0)
    assert len(orders) == 2
    assert orders[0].size == 60.0
    assert orders[0].wallet_address == "0x1"
    assert orders[0].decrypted_key == "secret"
    
    assert orders[1].size == 40.0
    assert orders[1].wallet_address == "0x2"
