"""Tests for StrategyTemplate — serialization round-trip and dataclass behavior."""

from backend.strategies.template_base import (
    EntryCriteria,
    ExitCriteria,
    RiskParameters,
    StrategyTemplate,
)


class TestEntryCriteria:
    def test_defaults(self):
        e = EntryCriteria(signal="test_signal")
        assert e.signal == "test_signal"
        assert e.confirmations == []
        assert e.market_regime_filter == []
        assert e.min_confidence == 0.5

    def test_to_dict(self):
        e = EntryCriteria(
            signal="z_score",
            confirmations=["volume_spike"],
            market_regime_filter=["bull"],
            min_confidence=0.7,
        )
        d = e.to_dict()
        assert d["signal"] == "z_score"
        assert d["confirmations"] == ["volume_spike"]
        assert d["market_regime_filter"] == ["bull"]
        assert d["min_confidence"] == 0.7

    def test_from_dict_roundtrip(self):
        e = EntryCriteria(
            signal="momentum_break",
            confirmations=["rsi_oversold", "macd_cross"],
            market_regime_filter=["bear", "sideways"],
            min_confidence=0.65,
        )
        d = e.to_dict()
        e2 = EntryCriteria.from_dict(d)
        assert e2.signal == e.signal
        assert e2.confirmations == e.confirmations
        assert e2.market_regime_filter == e.market_regime_filter
        assert e2.min_confidence == e.min_confidence


class TestExitCriteria:
    def test_defaults(self):
        e = ExitCriteria()
        assert e.take_profit_pct == 0.10
        assert e.stop_loss_pct == 0.05
        assert e.time_stop_minutes == 60
        assert e.signal_reversal is True

    def test_to_dict_roundtrip(self):
        e = ExitCriteria(
            take_profit_pct=0.15,
            stop_loss_pct=0.08,
            time_stop_minutes=120,
            signal_reversal=False,
        )
        d = e.to_dict()
        e2 = ExitCriteria.from_dict(d)
        assert e2.take_profit_pct == 0.15
        assert e2.stop_loss_pct == 0.08
        assert e2.time_stop_minutes == 120
        assert e2.signal_reversal is False


class TestRiskParameters:
    def test_defaults(self):
        r = RiskParameters()
        assert r.max_position_pct == 0.08
        assert r.max_portfolio_heat == 0.70
        assert r.kelly_fraction == 0.30

    def test_to_dict_roundtrip(self):
        r = RiskParameters(
            max_position_pct=0.05,
            max_portfolio_heat=0.50,
            kelly_fraction=0.25,
        )
        d = r.to_dict()
        r2 = RiskParameters.from_dict(d)
        assert r2.max_position_pct == 0.05
        assert r2.max_portfolio_heat == 0.50
        assert r2.kelly_fraction == 0.25


class TestStrategyTemplate:
    def _make_template(self) -> StrategyTemplate:
        return StrategyTemplate(
            template_id="longshot_no_bias",
            strategy_class="LongshotBiasStrategy",
            entry=EntryCriteria(
                signal="price_below_30c",
                confirmations=["no_token_available"],
                market_regime_filter=["bear", "sideways"],
                min_confidence=0.6,
            ),
            exit=ExitCriteria(
                take_profit_pct=0.23,
                stop_loss_pct=0.10,
                time_stop_minutes=1440,
                signal_reversal=True,
            ),
            risk=RiskParameters(
                max_position_pct=0.02,
                max_portfolio_heat=0.30,
                kelly_fraction=0.25,
            ),
            regime_effectiveness={
                "bear": 0.75,
                "sideways": 0.80,
                "bull": 0.40,
            },
            description="Buy NO tokens on longshot markets below 30c",
        )

    def test_to_dict(self):
        t = self._make_template()
        d = t.to_dict()
        assert d["template_id"] == "longshot_no_bias"
        assert d["strategy_class"] == "LongshotBiasStrategy"
        assert d["entry"]["signal"] == "price_below_30c"
        assert d["exit"]["take_profit_pct"] == 0.23
        assert d["risk"]["kelly_fraction"] == 0.25
        assert d["regime_effectiveness"]["bear"] == 0.75
        assert d["description"] == "Buy NO tokens on longshot markets below 30c"

    def test_from_dict_roundtrip(self):
        t = self._make_template()
        d = t.to_dict()
        t2 = StrategyTemplate.from_dict(d)
        assert t2.template_id == t.template_id
        assert t2.strategy_class == t.strategy_class
        assert t2.entry.signal == t.entry.signal
        assert t2.entry.confirmations == t.entry.confirmations
        assert t2.entry.market_regime_filter == t.entry.market_regime_filter
        assert t2.entry.min_confidence == t.entry.min_confidence
        assert t2.exit.take_profit_pct == t.exit.take_profit_pct
        assert t2.exit.stop_loss_pct == t.exit.stop_loss_pct
        assert t2.exit.time_stop_minutes == t.exit.time_stop_minutes
        assert t2.exit.signal_reversal == t.exit.signal_reversal
        assert t2.risk.max_position_pct == t.risk.max_position_pct
        assert t2.risk.max_portfolio_heat == t.risk.max_portfolio_heat
        assert t2.risk.kelly_fraction == t.risk.kelly_fraction
        assert t2.regime_effectiveness == t.regime_effectiveness
        assert t2.description == t.description

    def test_from_dict_minimal(self):
        """from_dict works with minimal data (defaults fill the rest)."""
        d = {
            "template_id": "minimal",
            "strategy_class": "MinimalStrategy",
            "entry": {"signal": "x"},
            "exit": {},
            "risk": {},
        }
        t = StrategyTemplate.from_dict(d)
        assert t.template_id == "minimal"
        assert t.entry.signal == "x"
        assert t.exit.take_profit_pct == 0.10  # default
        assert t.risk.kelly_fraction == 0.30  # default
        assert t.regime_effectiveness == {}
        assert t.description == ""

    def test_double_roundtrip(self):
        """Serializing twice produces identical output."""
        t = self._make_template()
        d1 = t.to_dict()
        t2 = StrategyTemplate.from_dict(d1)
        d2 = t2.to_dict()
        assert d1 == d2
