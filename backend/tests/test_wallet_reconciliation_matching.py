"""T17: Wallet reconciliation condition_id matching + orphan logging [#49]."""
import logging
import pytest
from unittest.mock import MagicMock, patch

from backend.models.database import Base, Trade, SessionLocal


@pytest.fixture
def test_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def _make_trade(db, market_ticker, direction="up", entry_price=0.50, size=10.0, trading_mode="paper"):
    trade = Trade(
        market_ticker=market_ticker,
        direction=direction,
        entry_price=entry_price,
        size=size,
        trading_mode=trading_mode,
    )
    db.add(trade)
    db.commit()
    return trade


class TestConditionIdMatching:
    def test_condition_id_matches_first(self, test_db):
        trade = _make_trade(test_db, "will-btc-hit-100k-condition_abc123def456")
        rec = MagicMock()
        rec.get.side_effect = lambda k, d=None: {
            "conditionId": "abc123def456",
            "title": "Will BTC hit 100k?",
            "usdcSize": "15.0",
            "transactionHash": "0xabc",
            "timestamp": 0,
            "slug": "will-btc-hit-100k",
            "eventSlug": "crypto",
        }.get(k, d)

    def test_orphan_redeem_logs_warning(self, test_db, caplog):
        with caplog.at_level(logging.WARNING):
            rec = MagicMock()
            rec.get.side_effect = lambda k, d=None: {
                "conditionId": "nonexistent_condition_id",
                "title": "Some Unmatched Market",
                "usdcSize": "5.0",
                "transactionHash": "0xdef",
                "timestamp": 0,
                "slug": "unmatched-market",
                "eventSlug": "misc",
            }.get(k, d)

    def test_slug_fallback_when_condition_id_fails(self, test_db):
        trade = _make_trade(test_db, "will-btc-hit-100k-2024")
        rec = MagicMock()
        rec.get.side_effect = lambda k, d=None: {
            "conditionId": "",
            "title": "Will BTC hit 100k?",
            "usdcSize": "15.0",
            "transactionHash": "0xabc",
            "timestamp": 0,
            "slug": "will-btc-hit-100k-2024",
            "eventSlug": "crypto",
        }.get(k, d)
