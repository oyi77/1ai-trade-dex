import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.core.outcome_repository import record_outcome
from backend.core.trading_calibration import TradingCalibration
from backend.core.thompson_sampler import ThompsonSampler
from backend.core.strategy_health import StrategyHealthMonitor
from backend.core.safe_param_tuner import SafeParamTuner

logger = logging.getLogger(__name__)

_calibration = TradingCalibration()
_sampler = ThompsonSampler()
_health_monitor = StrategyHealthMonitor()
_param_tuner = SafeParamTuner()


def _health_enabled() -> bool:
    try:
        from backend.config import settings
        return getattr(settings, "AGI_STRATEGY_HEALTH_ENABLED", True)
    except Exception:
        return True


def _load_persisted_weights(strategy: str, db: Session) -> None:
    try:
        from backend.models.database import StrategyConfig
        config = db.query(StrategyConfig).filter(
            StrategyConfig.strategy_name == strategy
        ).first()
        if config is None or not config.params:
            return
        params = json.loads(config.params) if isinstance(config.params, str) else config.params
        learned = params.get("learned_weights")
        if not learned:
            return
        ts_data = learned.get("thompson")
        if ts_data and isinstance(ts_data, list) and len(ts_data) == 2:
            _sampler._posteriors[strategy] = (float(ts_data[0]), float(ts_data[1]))
        cal_data = learned.get("calibration")
        if cal_data and isinstance(cal_data, list) and len(cal_data) == 2:
            bd = _calibration._betas.get(strategy)
            if bd is None:
                from backend.core.trading_calibration import BetaDistribution
                bd = BetaDistribution()
                _calibration._betas[strategy] = bd
            bd.alpha = float(cal_data[0])
            bd.beta = float(cal_data[1])
        logger.info("[OnlineLearner] Loaded persisted weights for '%s'", strategy)
    except Exception as e:
        logger.debug("[OnlineLearner] Could not load weights for '%s': %s", strategy, e)


def _persist_weights(strategy: str, db: Session) -> None:
    try:
        from backend.models.database import StrategyConfig
        config = db.query(StrategyConfig).filter(
            StrategyConfig.strategy_name == strategy
        ).first()
        if config is None:
            return
        params = json.loads(config.params) if isinstance(config.params, str) else (config.params or {})
        if isinstance(config.params, str):
            params = json.loads(config.params)
        elif config.params:
            params = dict(config.params)
        else:
            params = {}

        ts_alpha, ts_beta = _sampler._posteriors.get(strategy, (1.0, 1.0))
        cal_bd = _calibration._betas.get(strategy)
        cal_data = [cal_bd.alpha, cal_bd.beta] if cal_bd else [1.0, 1.0]

        params["learned_weights"] = {
            "thompson": [ts_alpha, ts_beta],
            "calibration": cal_data,
            "last_persisted_ts": datetime.now(timezone.utc).isoformat(),
        }
        config.params = json.dumps(params)
        db.commit()
        logger.info(
            "[OnlineLearner] Persisted weights for '%s': thompson=(%.1f,%.1f) cal=(%.1f,%.1f)",
            strategy, ts_alpha, ts_beta, cal_data[0], cal_data[1],
        )
    except Exception as e:
        logger.warning("[OnlineLearner] Failed to persist weights for '%s': %s", strategy, e)


class OnlineLearner:
    def on_trade_settled(self, trade, db: Session) -> None:
        strategy = getattr(trade, "strategy", None)
        if not strategy or strategy == "unknown":
            try:
                from backend.models.database import TradeContext
                ctx = db.query(TradeContext).filter(TradeContext.trade_id == trade.id).first()
                if ctx and ctx.strategy_name:
                    strategy = ctx.strategy_name
            except Exception:
                pass
        strategy = strategy or "general_scanner"

        _load_persisted_weights(strategy, db)

        outcome = record_outcome(trade, db)
        if outcome is None:
            logger.warning(f"[OnlineLearner] Failed to record outcome for trade {getattr(trade, 'id', '?')}")
            return

        prob = getattr(trade, "model_probability", None)
        result = getattr(trade, "result", None)
        if prob is not None and result in ("win", "loss"):
            actual = 1 if result == "win" else 0
            _calibration.record(strategy, prob, actual)
            _sampler.update(strategy, won=(result == "win"))

        _persist_weights(strategy, db)

        if _health_enabled():
            health = _health_monitor.assess(strategy, db)
            if health.get("status") == "killed":
                logger.warning(f"[OnlineLearner] Strategy '{strategy}' killed by health monitor")
                return

        _param_tuner.revert_if_degraded(strategy, db)

    def run_cycle(self, strategy: str, db: Session) -> None:
        _load_persisted_weights(strategy, db)

        if _health_enabled():
            health = _health_monitor.assess(strategy, db)
            if health.get("status") == "killed":
                return

        _param_tuner.revert_if_degraded(strategy, db)
        _param_tuner.tune(strategy, db)

    def get_allocation(self, strategies: list, total_capital: float = 1000.0) -> dict:
        return _sampler.allocate(strategies, total_capital)

    def get_calibrated_prob(self, strategy: str, raw_prob: float) -> float:
        return _calibration.calibrate_probability(strategy, raw_prob)

    def get_strategy_rankings(self) -> dict[str, float]:
        try:
            return self.get_allocation(
                ["btc_momentum", "weather_emos", "btc_oracle", "copy_trader",
                 "market_maker", "kalshi_arb", "bond_scanner", "whale_pnl",
                 "realtime_scanner"], total_capital=1.0)
        except Exception:
            return {}
