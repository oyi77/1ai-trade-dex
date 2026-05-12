import math
import json
from typing import Dict, Any
from sqlalchemy.orm import Session

from loguru import logger

from backend.models.outcome_tables import StrategyOutcome, ParamChange
from backend.models.database import StrategyConfig
from backend.core.outcome_repository import record_param_change, mark_param_reverted
from backend.core.walk_forward import WalkForwardValidator
from backend.config import settings


def _cfg(key: str, default=None):
    return getattr(settings, key, default) if hasattr(settings, key) else default


MAX_CHANGE_PCT = _cfg("SAFE_TUNER_MAX_CHANGE_PCT", 0.10)
MIN_TRADES_FOR_TUNING = _cfg("SAFE_TUNER_MIN_TRADES_FOR_TUNING", 20)
REVERT_SIGMA_THRESHOLD = _cfg("SAFE_TUNER_REVERT_SIGMA_THRESHOLD", 2.0)


def _sharpe(pnls):
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(variance) if variance > 0 else 1e-9
    return (mean / std) * math.sqrt(len(pnls))


def _recent_pnls(strategy: str, limit: int, db: Session):
    rows = (
        db.query(StrategyOutcome)
        .filter(StrategyOutcome.strategy == strategy)
        .order_by(StrategyOutcome.settled_at.desc())
        .limit(limit)
        .all()
    )
    return [r.pnl for r in rows if r.pnl is not None]


class SafeParamTuner:
    def tune(self, strategy: str, db: Session) -> Dict[str, Any]:
        pnls = _recent_pnls(strategy, MIN_TRADES_FOR_TUNING, db)
        if len(pnls) < MIN_TRADES_FOR_TUNING:
            return {}

        config = db.query(StrategyConfig).filter(
            StrategyConfig.strategy_name == strategy
        ).first()
        if not config or not config.params:
            return {}

        try:
            params = json.loads(config.params) if isinstance(config.params, str) else config.params
        except Exception:
            logger.exception(f"[SafeParamTuner] {strategy}: failed to parse strategy config params")
            return {}

        if not isinstance(params, dict):
            return {}

        pre_sharpe = _sharpe(pnls)
        changes = {}

        new_params = dict(params)
        for key, val in params.items():
            if not isinstance(val, (int, float)):
                continue
            if val == 0:
                continue
            direction = 1 if pre_sharpe >= 0 else -1
            delta = val * MAX_CHANGE_PCT * direction
            new_params[key] = val + delta

        validator = WalkForwardValidator()
        result = validator.validate_param_change(strategy, params, new_params, db)
        if not result.approved:
            logger.info(f"[SafeParamTuner] {strategy}: walk-forward rejected changes — {result.reason}")
            return {}

        for key, val in params.items():
            if not isinstance(val, (int, float)) or val == 0:
                continue
            new_val = new_params[key]
            params[key] = new_val
            record_param_change(strategy, key, float(val), float(new_val), db)
            changes[key] = {"old": val, "new": new_val}
            logger.info(f"[SafeParamTuner] {strategy}.{key}: {val:.4f} -> {new_val:.4f}")

        if changes:
            try:
                config.params = json.dumps(params)
                db.commit()
            except Exception as e:
                logger.error(f"[SafeParamTuner] Failed to save params for {strategy}: {e}")
                db.rollback()

        return changes

    def revert_if_degraded(self, strategy: str, db: Session) -> bool:
        pnls_recent = _recent_pnls(strategy, 20, db)
        if len(pnls_recent) < 10:
            return False

        last_change = (
            db.query(ParamChange)
            .filter(
                ParamChange.strategy == strategy,
                ParamChange.reverted_at is None,
            )
            .order_by(ParamChange.applied_at.desc())
            .first()
        )
        if not last_change:
            return False

        pre_sharpe = last_change.pre_change_sharpe or 0.0
        post_sharpe = _sharpe(pnls_recent)

        if pre_sharpe == 0.0:
            return False

        degradation = pre_sharpe - post_sharpe
        sigma = abs(pre_sharpe) * 0.1 or 1e-9

        if degradation > REVERT_SIGMA_THRESHOLD * sigma:
            config = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == strategy
            ).first()
            if config and config.params:
                try:
                    params = json.loads(config.params) if isinstance(config.params, str) else config.params
                    if isinstance(params, dict) and last_change.param_name in params:
                        params[last_change.param_name] = last_change.old_value
                        config.params = json.dumps(params)
                        db.commit()
                        mark_param_reverted(last_change.id, post_sharpe, db)
                        logger.warning(
                            f"[SafeParamTuner] Reverted {strategy}.{last_change.param_name} "
                            f"(sharpe {pre_sharpe:.3f} -> {post_sharpe:.3f})"
                        )
                        return True
                except Exception as e:
                    logger.error(f"[SafeParamTuner] Revert failed for {strategy}: {e}")
                    db.rollback()

        return False
