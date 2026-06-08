from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.database import Base, Trade as TradeModel
from backend.core.bundle_reconciliation import (
    reconcile_bundle_pnl,
    detect_incomplete_bundles,
    count_open_incomplete_bundles,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _trade_record(db, bundle_id=None, leg_idx=None, leg_cnt=None, direction="YES",
                  settled=False, pnl=None, result="pending", strategy="arb_scanner",
                  mode="live", size=10.0, entry_price=0.50, market_ticker="mkt",
                  filled_size=None, fill_price=None, fee=None, role="taker",
                  maker_size=None, taker_size=None, slippage=None, source="bot",
                  platform="polymarket", confidence=0.5):
    t = TradeModel(
        arb_bundle_id=bundle_id,
        arb_leg_index=leg_idx,
        arb_leg_count=leg_cnt,
        direction=direction,
        settled=settled,
        pnl=pnl,
        result=result,
        strategy=strategy,
        trading_mode=mode,
        entry_price=entry_price,
        size=size,
        market_ticker=market_ticker,
        filled_size=filled_size,
        fill_price=fill_price,
        fee=fee,
        role=role,
        maker_size=maker_size,
        taker_size=taker_size,
        slippage=slippage,
        source=source,
        platform=platform,
        confidence=confidence,
    )
    db.add(t)
    db.flush()
    return t


def _make_mock(bundle_id=None, leg_idx=None, leg_cnt=None, direction="YES",
               settled=False, pnl=None, result="pending", strategy="arb_scanner",
               mode="live", size=10.0, entry_price=0.50, market_ticker="mkt"):
    return SimpleNamespace(
        id=(leg_idx or 1),
        arb_bundle_id=bundle_id,
        arb_leg_index=leg_idx,
        arb_leg_count=leg_cnt,
        direction=direction,
        settled=settled,
        pnl=pnl,
        result=result,
        strategy=strategy,
        trading_mode=mode,
        entry_price=entry_price,
        size=size,
        market_ticker=market_ticker,
    )


class TestBundlePnl:
    def test_settled_both_legs_net_near_zero_profitable(self):
        bundle = "arb-1-cond"
        yes = _make_mock(bundle_id=bundle, leg_idx=1, leg_cnt=2, direction="YES",
                         settled=True, result="win", pnl=29.98, entry_price=0.40, size=50.0)
        no = _make_mock(bundle_id=bundle, leg_idx=2, leg_cnt=2, direction="NO",
                        settled=True, result="win", pnl=29.98, entry_price=0.40, size=50.0)

        result = reconcile_bundle_pnl([yes, no])
        assert result["bundle_id"] == bundle
        assert result["settled_legs"] == 2
        assert result["bundle_pnl"] == pytest.approx(59.96)
        assert result["is_complete"] is True

    def test_settled_both_legs_net_loss(self):
        bundle = "arb-2-cond"
        yes = _make_mock(bundle_id=bundle, leg_idx=1, leg_cnt=2, direction="YES",
                         settled=True, result="loss", pnl=-10.0)
        no = _make_mock(bundle_id=bundle, leg_idx=2, leg_cnt=2, direction="NO",
                        settled=True, result="loss", pnl=-40.0)

        result = reconcile_bundle_pnl([yes, no])
        assert result["bundle_pnl"] == pytest.approx(-50.0)

    def test_one_leg_settled_one_unsettled(self):
        bundle = "arb-3-cond"
        yes = _make_mock(bundle_id=bundle, leg_idx=1, leg_cnt=2, direction="YES",
                         settled=True, result="win", pnl=30.0)
        no = _make_mock(bundle_id=bundle, leg_idx=2, leg_cnt=2, direction="NO",
                        settled=False, pnl=None)

        result = reconcile_bundle_pnl([yes, no])
        assert result["settled_legs"] == 1
        assert result["total_legs"] == 2
        assert result["is_complete"] is False
        assert result["bundle_pnl"] == pytest.approx(30.0)


class TestIncompleteDetection:
    def test_bundle_missing_no_leg_detected(self):
        bundle = "arb-bad-1"
        yes = _make_mock(bundle_id=bundle, leg_idx=1, leg_cnt=2, direction="YES",
                         settled=False, result="pending")

        incomplete = detect_incomplete_bundles([yes])
        assert len(incomplete) == 1
        assert incomplete[0]["bundle_id"] == bundle
        assert incomplete[0]["legs_found"] == 1
        assert incomplete[0]["legs_expected"] == 2

    def test_complete_pair_not_detected(self):
        bundle = "arb-ok-1"
        yes = _make_mock(bundle_id=bundle, leg_idx=1, leg_cnt=2, direction="YES")
        no = _make_mock(bundle_id=bundle, leg_idx=2, leg_cnt=2, direction="NO")

        incomplete = detect_incomplete_bundles([yes, no])
        assert len(incomplete) == 0

    def test_non_arb_trades_ignored(self):
        normal = _make_mock(bundle_id=None)

        incomplete = detect_incomplete_bundles([normal])
        assert len(incomplete) == 0


class TestIncompleteGate:
    def test_zero_incomplete_returns_zero(self, db_session):
        assert count_open_incomplete_bundles(db_session, mode="live") == 0

    def test_one_incomplete_returns_one(self, db_session):
        _trade_record(db_session, bundle_id="arb-inc-1", leg_idx=1, leg_cnt=2,
                      direction="YES", settled=False, result="pending", mode="live")
        assert count_open_incomplete_bundles(db_session, mode="live") == 1

    def test_respects_mode_filter(self, db_session):
        _trade_record(db_session, bundle_id="arb-inc-1", leg_idx=1, leg_cnt=2,
                      direction="YES", settled=False, result="pending", mode="paper")
        assert count_open_incomplete_bundles(db_session, mode="live") == 0
        assert count_open_incomplete_bundles(db_session, mode="paper") == 1
