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

    read_db = _FakeDB([
        SimpleNamespace(address="0xabc"),
        SimpleNamespace(address="0xdef"),
    ])
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
        return [{"pnl": 10.0, "size": 20.0, "timestamp": 1}] if wallet == "0xabc" else []

    discovery = WhaleDiscovery()
    with patch("backend.db.utils.get_db_session", fake_get_db_session), patch.object(
        discovery,
        "_fetch_history",
        side_effect=fake_fetch_history,
    ):
        results = await discovery.discover(min_trades=1)

    assert len(results) == 1
    assert results[0]["wallet"] == "0xabc"
    assert results[0]["trade_count"] == 1
    assert results[0]["score"] > 0
    assert write_rows[0].whale_score == results[0]["score"]


@pytest.mark.asyncio
async def test_whale_frontrun_resolves_tokens_after_db_close():
    from backend.modules.data_feeds.whale_frontrun import WhaleFrontrun

    fake_db = _FakeDB([SimpleNamespace(address="0xabc")])

    @contextmanager
    def fake_get_db_session():
        try:
            yield fake_db
        finally:
            fake_db.close()

    class _FakeResponse:
        status_code = 200

        def json(self):
            return [{"asset": "token-1"}]

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            assert fake_db.closed is True
            return _FakeResponse()

    strategy = WhaleFrontrun()
    strategy.register_with_event_bus = AsyncMock()

    with patch("backend.db.utils.get_db_session", fake_get_db_session), patch(
        "backend.modules.data_feeds.whale_frontrun.httpx.AsyncClient",
        _FakeAsyncClient,
    ), patch("backend.modules.data_feeds.whale_frontrun.asyncio.sleep", AsyncMock()):
        await strategy._resolve_whale_tokens()

    assert strategy.subscribed_tokens == {"token-1"}
    assert strategy._tokens_resolved is True


@pytest.mark.asyncio
async def test_copy_trader_get_active_wallets_uses_short_lived_snapshot_session():
    from backend.modules.execution.copy_trader import CopyTraderStrategy

    snapshot_db = _FakeDB([
        SimpleNamespace(address="0xuser1"),
        SimpleNamespace(address="0xuser2"),
    ])

    @contextmanager
    def fake_get_db_session():
        try:
            yield snapshot_db
        finally:
            snapshot_db.close()

    traders = [
        SimpleNamespace(user="0xleader", score=90.0),
        SimpleNamespace(user="0xuser2", score=85.0),
    ]

    strategy = CopyTraderStrategy(max_wallets=5, min_score=30.0)
    strategy._engine._scorer = SimpleNamespace(fetch_and_score=AsyncMock(return_value=traders))
    ctx = SimpleNamespace(
        params={"max_wallets": 5, "min_score": 30.0},
        logger=MagicMock(),
        db=MagicMock(),
    )
    ctx.db.query.side_effect = AssertionError("_get_active_wallets should not use ctx.db for wallet snapshot")

    with patch("backend.db.utils.get_db_session", fake_get_db_session):
        wallets = await strategy._get_active_wallets(ctx)

    assert snapshot_db.closed is True
    assert wallets == ["0xuser1", "0xuser2", "0xleader"]


@pytest.mark.asyncio
async def test_auto_add_profitable_wallets_rolls_back_before_leaderboard_await():
    from backend.core.wallet_auto_discovery import auto_add_profitable_wallets
    from backend.models.database import WalletConfig

    class _WalletDB(_FakeDB):
        def __init__(self, rows):
            super().__init__(rows)
            self.rollback_called = False
            self.added = []
            self.committed = False

        def query(self, model):
            if model is WalletConfig:
                return _WalletConfigQuery(self.rows, self.added)
            return super().query(model)

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

        def filter(self, *args, **_kwargs):
            for arg in args:
                right = getattr(arg, "right", None)
                value = getattr(right, "value", None)
                if value is not None:
                    self._address = value
            return self

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
        "backend.core.wallet_auto_discovery.auto_suggest_wallets_to_copy",
        side_effect=fake_auto_suggest,
    ):
        result = await auto_add_profitable_wallets(db=db, max_wallets=1, auto_enable=True)

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
    with patch("backend.ai.strategy_composer.SessionLocal", side_effect=fake_session_local), patch.object(
        composer,
        "_generate_with_claude",
        side_effect=fake_generate,
    ), patch.object(
        composer,
        "_validate_and_register",
        return_value={"strategy_name": "demo"},
    ) as validate_mock:
        result = await composer.compose_new_strategy(db=write_db)

    assert result == {"strategy_name": "demo"}
    validate_mock.assert_called_once_with({"strategy_name": "demo", "code": "print('x')"}, write_db)
