import pytest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def query(self, _model):
        return _FakeQuery(self.rows)

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_whale_discovery_closes_snapshot_session_before_fetch_history():
    from backend.core.whale_discovery import WhaleDiscovery

    read_db = _FakeDB(
        [
            SimpleNamespace(address="0xabc"),
            SimpleNamespace(address="0xdef"),
        ]
    )
    write_rows = [
        SimpleNamespace(address="0xabc", whale_score=None),
    ]
    write_db = _FakeDB(write_rows)
    dbs = iter([read_db, write_db])

    @contextmanager
    def fake_get_db_session():
        db = next(dbs)
        try:
            yield db
        finally:
            db.close()

    async def fake_fetch_history(wallet: str):
        assert read_db.closed is True
        return (
            [{"pnl": 10.0, "size": 20.0, "timestamp": 1}] if wallet == "0xabc" else []
        )

    discovery = WhaleDiscovery()
    with (
        patch("backend.db.utils.get_db_session", fake_get_db_session),
        patch.object(
            discovery,
            "_fetch_history",
            side_effect=fake_fetch_history,
        ),
    ):
        results = await discovery.discover(min_trades=1)

    assert len(results) == 1
    assert results[0]["wallet"] == "0xabc"
    assert results[0]["trade_count"] == 1
    assert results[0]["score"] > 0
    assert write_rows[0].whale_score == results[0]["score"]


@pytest.mark.asyncio
async def test_auto_add_profitable_wallets_rolls_back_before_leaderboard_await():
    from backend.core.wallet.wallet_auto_discovery import auto_add_profitable_wallets
    from backend.models.database import WalletConfig

    class _WalletDB(_FakeDB):
        def __init__(self, rows):
            super().__init__(rows)
            self.rollback_called = False
            self.added = []
            self.committed = False

        def query(self, model):
            if model is WalletConfig:
                q = _WalletConfigQuery(self.rows, self.added)
                q._is_column_query = False
                return q
            q = _WalletConfigQuery(self.rows, self.added)
            q._is_column_query = True
            return q

        def rollback(self):
            self.rollback_called = True

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.committed = True

    class _WalletConfigQuery(_FakeQuery):
        def __init__(self, rows, added):
            super().__init__(rows)
            self._added = added
            self._address = None
            self._is_column_query = False

        def filter(self, *args, **_kwargs):
            for arg in args:
                right = getattr(arg, "right", None)
                value = getattr(right, "value", None)
                if value is not None:
                    self._address = value
            return self

        def all(self):
            rows = super().all()
            if self._is_column_query:
                return [(getattr(r, "address", None),) for r in rows]
            return rows

        def first(self):
            if self._address is None:
                return super().first()
            for row in [*self._rows, *self._added]:
                if getattr(row, "address", None) == self._address:
                    return row
            return None

    db = _WalletDB([SimpleNamespace(address="0xabc", enabled=True)])

    async def fake_auto_suggest(_db, current_wallets, limit):
        assert db.rollback_called is True
        assert current_wallets == ["0xabc"]
        return [{"address": "0xdef", "pnl": 1200, "win_rate": 0.7}]

    with patch(
        "backend.core.wallet.wallet_auto_discovery.auto_suggest_wallets_to_copy",
        side_effect=fake_auto_suggest,
    ):
        result = await auto_add_profitable_wallets(
            db=db, max_wallets=1, auto_enable=True
        )

    assert result["added_count"] == 1
    assert db.committed is True
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_strategy_composer_closes_read_session_before_llm_await():
    from backend.ai.strategy_composer import StrategyComposer

    read_db = _FakeDB([])
    write_db = MagicMock()

    def fake_session_local():
        return read_db

    async def fake_generate(_prompt):
        assert read_db.closed is True
        return {"strategy_name": "demo", "code": "print('x')"}

    composer = StrategyComposer()
    with (
        patch(
            "backend.ai.strategy_composer.SessionLocal", side_effect=fake_session_local
        ),
        patch.object(
            composer,
            "_generate_with_claude",
            side_effect=fake_generate,
        ),
        patch.object(
            composer,
            "_validate_and_register",
            return_value={"strategy_name": "demo"},
        ) as validate_mock,
    ):
        result = await composer.compose_new_strategy(db=write_db)

    assert result == {"strategy_name": "demo"}
    validate_mock.assert_called_once_with(
        {"strategy_name": "demo", "code": "print('x')"}, write_db
    )


def test_strategy_composer_parses_compilable_template():
    from backend.ai.strategy_composer import StrategyComposer

    response = """
STRATEGY_NAME: demo_edge_strategy
DESCRIPTION: Demo generated strategy.
CATEGORY: crypto
DEFAULT_PARAMS: {"min_volume": 1000}
MARKET_FILTER: m.volume > params["min_volume"]
STRATEGY_BODY: result.decisions_recorded += 1
"""

    parsed = StrategyComposer()._parse_response(response)

    assert parsed is not None
    assert "{class_name}" not in parsed["code"]
    assert "{strategy_name}" not in parsed["code"]
    assert "class DemoEdgeStrategy" in parsed["code"]
    compile(parsed["code"], "<demo_edge_strategy>", "exec")
