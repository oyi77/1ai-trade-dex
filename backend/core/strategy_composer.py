from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import StrategyBlock, MarketRegime
from backend.models.kg_models import Base, ExperimentRecord

from loguru import logger


class ComposedStrategy:
    def __init__(
        self,
        name: str,
        blocks: list[StrategyBlock],
        status: str = "draft",
        experiment_id: Optional[str] = None,
        kg_context: Optional[dict] = None,
    ):
        self.name = name
        self.blocks = blocks
        self.status = status
        self.experiment_id = experiment_id
        self.created_at = datetime.now(timezone.utc)
        # KG context injected at composition time; used by StrategySynthesizer
        # to enrich LLM prompts with regime history and strategy performance.
        self.kg_context: dict = kg_context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "blocks": [b.to_dict() for b in self.blocks],
            "status": self.status,
            "experiment_id": self.experiment_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComposedStrategy:
        blocks = [StrategyBlock.from_dict(b) for b in d["blocks"]]
        return cls(
            name=d["name"],
            blocks=blocks,
            status=d.get("status", "draft"),
            experiment_id=d.get("experiment_id"),
        )


class ValidationResult:
    def __init__(self, valid: bool, errors: list[str] | None = None):
        self.valid = valid
        self.errors = errors or []

    def __bool__(self) -> bool:
        return self.valid


class BacktestResult:
    def __init__(
        self,
        strategy_name: str,
        regime: str,
        trades: int = 0,
        win_rate: float = 0.0,
        pnl: float = 0.0,
    ):
        self.strategy_name = strategy_name
        self.regime = regime
        self.trades = trades
        self.win_rate = win_rate
        self.pnl = pnl


BLOCK_CATALOG = {
    "signal_source": [
        "whale_tracker_signal",
        "btc_momentum_signal",
        "weather_signal",
        "oracle_signal",
    ],
    "filter": ["min_edge_005", "min_confidence_07", "volume_filter"],
    "position_sizer": ["kelly_sizer", "fixed_01", "fixed_005", "half_kelly"],
    "risk_rule": ["max_1pct", "max_2pct", "daily_loss_5pct", "max_drawdown_10pct"],
    "exit_rule": [
        "take_profit_10pct",
        "take_profit_20pct",
        "stop_loss_5pct",
        "trailing_stop_3pct",
    ],
}


class StrategyComposer:
    def __init__(
        self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"
    ):
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True

    def close(self):
        if self._owns_session:
            self._session.close()

    def compose(
        self, blocks: list[StrategyBlock], name: str, kg_context: dict | None = None
    ) -> ComposedStrategy:
        """Compose a strategy from blocks.

        ``kg_context`` carries regime history and strategy performance data read
        from the KnowledgeGraph.  It is stored on the composed strategy so that
        downstream callers (e.g. StrategySynthesizer) can inject it into LLM
        prompts without re-querying the KG.
        """
        composed = ComposedStrategy(name=name, blocks=blocks, status="draft")
        if kg_context:
            composed.kg_context = kg_context
        return composed

    def validate_composition(self, composed: ComposedStrategy) -> ValidationResult:
        errors = []

        if not composed.blocks:
            errors.append("no_blocks: at least one block required")
            return ValidationResult(False, errors)

        block_types = [b.signal_source for b in composed.blocks if b.signal_source]
        if not block_types:
            errors.append("missing_signal_source: no signal source block found")

        has_risk_rule = any(b.risk_rule for b in composed.blocks)
        if not has_risk_rule:
            errors.append("missing_risk_rule: risk rule is required")

        has_position_sizer = any(b.position_sizer for b in composed.blocks)
        if not has_position_sizer:
            errors.append("missing_position_sizer: position sizer is required")

        for b in composed.blocks:
            if (
                b.signal_source
                and b.signal_source not in BLOCK_CATALOG["signal_source"]
            ):
                errors.append(f"invalid_signal_source: {b.signal_source}")
            if b.risk_rule and b.risk_rule not in BLOCK_CATALOG["risk_rule"]:
                errors.append(f"invalid_risk_rule: {b.risk_rule}")
            if (
                b.position_sizer
                and b.position_sizer not in BLOCK_CATALOG["position_sizer"]
            ):
                errors.append(f"invalid_position_sizer: {b.position_sizer}")

        if len(block_types) != len(set(block_types)):
            errors.append("circular_reference: duplicate signal sources detected")

        return ValidationResult(len(errors) == 0, errors)

    def backtest_composed(
        self, composed: ComposedStrategy, regime: MarketRegime
    ) -> BacktestResult:
        from datetime import datetime, timezone, timedelta
        from backend.core.backtester import BacktestEngine, BacktestConfig

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=30)

        bt_config = BacktestConfig(
            strategy_name=composed.name,
            start_date=start_dt,
            end_date=end_dt,
            initial_bankroll=1000.0,
        )
        engine = BacktestEngine(bt_config)
        try:
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                engine.run(db=self._session)
            )
            return BacktestResult(
                strategy_name=composed.name,
                regime=regime.value,
                trades=result.total_trades,
                win_rate=result.win_rate,
                pnl=result.total_pnl,
            )
        except Exception:
            logger.exception(
                "[StrategyComposer] Backtest failed for '%s'", composed.name
            )
            return BacktestResult(
                strategy_name=composed.name,
                regime=regime.value,
                trades=0,
                win_rate=0.0,
                pnl=0.0,
            )

    def register_composed(self, composed: ComposedStrategy) -> str:
        validation = self.validate_composition(composed)
        if not validation:
            raise ValueError(
                f"Cannot register invalid composition: {validation.errors}"
            )

        existing = (
            self._session.query(ExperimentRecord).filter_by(name=composed.name).first()
        )
        if existing:
            return existing.name

        experiment = ExperimentRecord(
            name=composed.name,
            strategy_composition=composed.to_dict(),
            status="shadow",
        )
        self._session.add(experiment)
        self._session.commit()
        composed.status = "shadow"
        composed.experiment_id = str(experiment.id)
        return str(experiment.id)
