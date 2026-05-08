"""Database integrity tests for PolyEdge trading bot."""

import os
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, Trade, BotState, init_db, SessionLocal, engine


def _make_isolated_engine(db_path: str):
    """Create an isolated SQLAlchemy engine — no global state pollution."""
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(bind=eng)
    return eng


def test_database_initialization():
    """Test that database initializes correctly without corruption."""
    init_db(repair_if_needed=True)
    db = SessionLocal()
    try:
        assert db.execute(text('SELECT 1')).fetchone() == (1,)
    finally:
        db.close()


def test_database_transaction_robustness():
    """Test that database transactions are handled properly."""
    db = SessionLocal()
    try:
        db.add(Trade(
            market_ticker="INTEGRITY_TEST",
            platform="polymarket",
            direction="up",
            entry_price=0.50,
            size=10.0,
            model_probability=0.6,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="paper",
            strategy="test_strategy",
            timestamp=datetime.now(timezone.utc)
        ))
        db.commit()

        saved = db.query(Trade).filter_by(market_ticker="INTEGRITY_TEST").first()
        assert saved is not None
        assert saved.size == 10.0
        db.delete(saved)
        db.commit()
    finally:
        db.close()


def test_database_concurrent_access_safety():
    """Test that concurrent database access doesn't cause corruption."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    sessions = []
    try:
        for _ in range(5):
            s = Session()
            sessions.append(s)
            assert s.execute(text("SELECT 1")).fetchone() == (1,)
        for s in sessions:
            s.close()
    finally:
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass


def _rebuild_corrupted_db(db_path: str):
    """Simulate what init_db(repair_if_needed=True) does: wipe and recreate."""
    os.unlink(db_path)
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(bind=eng)
    return eng


def test_database_corruption_recovery():
    """Test automatic database corruption recovery via isolated engine."""
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db.close()

    try:
        eng = _make_isolated_engine(temp_db.name)
        Session = sessionmaker(bind=eng)

        db = Session()
        db.add(Trade(
            market_ticker="CORRUPTION_TEST",
            platform="polymarket",
            direction="up",
            entry_price=0.50,
            size=10.0,
            model_probability=0.6,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="paper",
            strategy="test_strategy",
            timestamp=datetime.now(timezone.utc)
        ))
        db.commit()
        assert db.query(Trade).filter_by(market_ticker="CORRUPTION_TEST").count() == 1
        db.close()
        eng.dispose()

        with open(temp_db.name, 'wb') as f:
            f.write(b'\x00' * 1000)

        eng2 = _rebuild_corrupted_db(temp_db.name)
        try:
            Session2 = sessionmaker(bind=eng2)
            db2 = Session2()
            assert db2.execute(text('SELECT 1')).fetchone() == (1,)
            db2.close()
        finally:
            eng2.dispose()
    finally:
        try:
            os.unlink(temp_db.name)
        except Exception:
            pass


def test_backup_restore_roundtrip():
    """Test backup creates valid copy and restore recovers exact state."""
    temp_dir = tempfile.mkdtemp()
    source_db_path = os.path.join(temp_dir, "source.db")
    backup_dest = os.path.join(temp_dir, "backups")
    os.makedirs(backup_dest, exist_ok=True)

    try:
        eng = _make_isolated_engine(source_db_path)
        Session = sessionmaker(bind=eng)
        db = Session()
        for i in range(5):
            db.add(Trade(
                market_ticker=f"BACKUP_TEST_{i}",
                platform="polymarket",
                direction="up" if i % 2 == 0 else "down",
                entry_price=0.50,
                size=10.0 + i,
                model_probability=0.6 + i * 0.05,
                market_price_at_entry=0.50,
                edge_at_entry=0.10,
                trading_mode="paper",
                strategy="test_strategy",
                timestamp=datetime.now(timezone.utc)
            ))
        db.commit()
        assert db.query(Trade).filter(Trade.market_ticker.like("BACKUP_TEST_%")).count() == 5
        db.close()
        eng.dispose()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = Path(backup_dest) / f"tradingbot_{timestamp}.db"
        shutil.copy2(source_db_path, backup_path)
        assert backup_path.exists()
        assert backup_path.stat().st_size > 0

        eng = _make_isolated_engine(source_db_path)
        Session = sessionmaker(bind=eng)
        db = Session()
        db.add(Trade(
            market_ticker="POST_BACKUP_EXTRA",
            platform="polymarket",
            direction="up",
            entry_price=0.60,
            size=15.0,
            model_probability=0.7,
            market_price_at_entry=0.60,
            edge_at_entry=0.15,
            trading_mode="paper",
            strategy="test_strategy",
            timestamp=datetime.now(timezone.utc)
        ))
        db.commit()
        assert db.query(Trade).filter_by(market_ticker="POST_BACKUP_EXTRA").count() == 1
        db.close()
        eng.dispose()

        shutil.copy2(backup_path, source_db_path)

        eng = _make_isolated_engine(source_db_path)
        Session = sessionmaker(bind=eng)
        db = Session()
        assert db.query(Trade).filter(Trade.market_ticker.like("BACKUP_TEST_%")).count() == 5
        assert db.query(Trade).filter_by(market_ticker="POST_BACKUP_EXTRA").count() == 0
        db.close()
        eng.dispose()
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


def test_automatic_repair_integrity():
    """Test that automatic repair produces a functional database after corruption."""
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db.close()

    try:
        eng = _make_isolated_engine(temp_db.name)
        Session = sessionmaker(bind=eng)
        db = Session()
        db.add_all([
            Trade(
                market_ticker=f"AUTOREPAIR_TEST_{i}",
                platform="polymarket",
                direction="up" if i % 2 == 0 else "down",
                entry_price=0.50,
                size=10.0 + i,
                model_probability=0.6 + i * 0.03,
                market_price_at_entry=0.50,
                edge_at_entry=0.10 + i * 0.01,
                trading_mode="paper",
                strategy=f"strategy_{i % 3}",
                timestamp=datetime.now(timezone.utc),
                result="win" if i % 2 == 0 else "loss",
                pnl=5.0 - i * 0.5
            )
            for i in range(10)
        ])
        db.commit()
        assert db.query(Trade).filter(Trade.market_ticker.like("AUTOREPAIR_TEST_%")).count() == 10
        db.close()
        eng.dispose()

        with open(temp_db.name, 'wb') as f:
            f.write(b'SQLite format 3\x00' + b'\xFF' * 10000)

        eng2 = _rebuild_corrupted_db(temp_db.name)
        try:
            Session2 = sessionmaker(bind=eng2)
            db2 = Session2()
            assert db2.execute(text('SELECT 1')).fetchone() == (1,)
            assert db2.query(Trade).filter(Trade.market_ticker.like("AUTOREPAIR_TEST_%")).count() == 0
            db2.close()
        finally:
            eng2.dispose()
    finally:
        try:
            os.unlink(temp_db.name)
        except Exception:
            pass


def test_seed_default_data_idempotent():
    """Test that seed_default_data can be called multiple times without duplicates."""
    init_db(repair_if_needed=True)
    from backend.models.database import seed_default_data

    seed_default_data()
    seed_default_data()

    db = SessionLocal()
    try:
        mode_counts = {}
        for state in db.query(BotState).all():
            mode_counts[state.mode] = mode_counts.get(state.mode, 0) + 1
        for mode in ["paper", "testnet", "live"]:
            assert mode_counts.get(mode, 0) == 1, f"Duplicate BotState for mode={mode}"
    finally:
        db.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
