"""Minimal tests for SignalLogRepository query methods."""

from datetime import datetime, timezone

from backend.models.signal_log import SignalLog
from backend.repositories.signal_log_repository import SignalLogRepository


class TestSignalLogRepository:
    def test_market_time_series(self, db):
        """Query logs for a specific market, ordered by timestamp desc."""
        now = datetime.now(timezone.utc)
        logs = [
            SignalLog(
                timestamp=now, market_id="M1", market_mid=0.52,
                strategy="alpha", edge_pp=0.05, filled=True, pnl=1.0,
            ),
            SignalLog(
                timestamp=now, market_id="M1", market_mid=0.54,
                strategy="alpha", edge_pp=0.03, filled=True, pnl=2.0,
            ),
            SignalLog(
                timestamp=now, market_id="M2", market_mid=0.64,
                strategy="beta", edge_pp=0.08, filled=False, pnl=None,
            ),
        ]
        db.add_all(logs)
        db.commit()

        repo = SignalLogRepository(db=db)
        result, elapsed = repo.market_time_series("M1", limit=10)

        assert len(result) == 2
        assert all(r.market_id == "M1" for r in result)
        assert elapsed >= 0.0

    def test_open_signals_needing_settlement(self, db):
        """Finds filled signals where pnl is still NULL."""
        now = datetime.now(timezone.utc)
        logs = [
            SignalLog(
                timestamp=now, market_id="M1", market_mid=0.50,
                strategy="alpha", filled=True, pnl=None,
            ),
            SignalLog(
                timestamp=now, market_id="M2", market_mid=0.60,
                strategy="alpha", filled=True, pnl=5.0,
            ),
            SignalLog(
                timestamp=now, market_id="M3", market_mid=0.70,
                strategy="alpha", filled=False, pnl=None,
            ),
        ]
        db.add_all(logs)
        db.commit()

        repo = SignalLogRepository(db=db)
        pending, _ = repo.open_signals_needing_settlement()

        # Only filled + pnl=None should appear
        assert len(pending) == 1
        assert pending[0].market_id == "M1"
        assert pending[0].filled is True
        assert pending[0].pnl is None
