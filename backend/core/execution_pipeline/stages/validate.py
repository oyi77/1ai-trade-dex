from loguru import logger

from backend.core.execution_pipeline.base import (
    BaseExecutionStage,
    ExecutionStageManifest,
)
from backend.core.execution_pipeline.registry import registry
from backend.core.risk.risk_manager import RiskManager


class ValidationStage(BaseExecutionStage):
    @classmethod
    def manifest(cls):
        return ExecutionStageManifest(
            name="validation",
            display_name="Risk Validation",
            version="1.1.0",
            mode="*",
            order=1,
            required_env_vars=[],
            tags=["validation", "risk", "dedup"],
        )

    def __init__(self):
        self.risk_manager = RiskManager()

    def validate(self, decision, ctx):
        size = float(decision.get("size", 0.0))
        current_exposure = ctx.get("current_exposure", 0.0)
        bankroll = ctx.get("bankroll", 0.0)
        confidence = float(decision.get("confidence", 0.0))
        market_ticker = decision.get("market_ticker")
        mode = ctx.get("mode", "paper")
        strategy_name = ctx.get("strategy_name", "unknown")
        direction = decision.get("direction")
        token_id = decision.get("token_id")
        db = ctx.get("db")

        # ── Loss streak circuit breaker ──
        if db is not None and strategy_name != "unknown":
            try:
                from backend.config import settings
                from sqlalchemy import text as _sql_text

                limit = getattr(settings, "CONSECUTIVE_LOSS_LIMIT", 5)
                recent = db.execute(
                    _sql_text(
                        "SELECT result FROM trades "
                        "WHERE strategy = :strat AND trading_mode = :mode "
                        "AND settled = 1 "
                        "ORDER BY id DESC LIMIT :lim"
                    ),
                    {"strat": strategy_name, "mode": mode, "lim": limit},
                ).fetchall()

                if len(recent) >= limit:
                    streak = all(
                        (r[0] or "").lower() in ("loss", "lost", "0", "false")
                        for r in recent
                    )
                    if streak:
                        logger.warning(
                            "[validation] LOSS STREAK: {} lost {} in a row — blocking trade",
                            strategy_name, limit,
                        )
                        return False
            except Exception as exc:
                logger.debug(f"[validation] Loss streak check failed: {exc}")

        # ── Permanent Fix: prevent duplicate trades on same token_id ──
        if db is not None and token_id:
            try:
                from sqlalchemy import text as _sql_text
                existing = db.execute(
                    _sql_text(
                        "SELECT id FROM trades "
                        "WHERE token_id = :tid AND trading_mode = :mode "
                        "AND status NOT IN ('closed', 'SETTLED', 'cancelled', 'error', 'closed_errored')"
                    ),
                    {"tid": token_id, "mode": mode},
                ).fetchone()
                if existing:
                    logger.warning(
                        f"[ValidationStage] DUPLICATE BLOCKED: token_id={token_id} "
                        f"mode={mode} already has open trade id={existing[0]}"
                    )
                    return False
            except Exception as e:
                logger.debug(f"[ValidationStage] dedup check failed (non-fatal): {e}")

        # ── Size validation: reject zero, negative, or absurdly large orders ──
        if size <= 0:
            logger.warning("[ValidationStage] BLOCKED: size={:.2f} is zero/negative", size)
            return False
        if bankroll > 0 and size > bankroll * 0.5:
            logger.warning(
                "[ValidationStage] BLOCKED: size={:.2f} > 50% of bankroll={:.2f}",
                size, bankroll,
            )
            return False

        # ── Edge re-validation: reject trades below edge threshold ──
        from backend.config import settings as _settings
        edge = float(decision.get("edge", 0.0))
        min_edge = float(getattr(_settings, "MIN_EDGE_PP", 6.0)) / 100.0
        if edge > 0 and edge < min_edge:
            logger.warning(
                "[ValidationStage] EDGE BLOCKED: edge={:.4f} < min={:.4f} for {}",
                edge, min_edge, market_ticker,
            )
            return False

        risk_decision = self.risk_manager.validate_trade(
            size=size,
            current_exposure=current_exposure,
            bankroll=bankroll,
            confidence=confidence,
            market_ticker=market_ticker,
            mode=mode,
            strategy_name=strategy_name,
            direction=direction,
        )

        return risk_decision.allowed

    def execute(self, decision, ctx):
        return {"validation_passed": True}

    def record(self, decision, result, ctx):
        market_ticker = decision.get("market_ticker", "unknown")
        passed = result.get("validation_passed", False)
        logger.info(
            "[ValidationStage] recorded: market={} passed={}",
            market_ticker,
            passed,
        )


registry.plugin(ValidationStage)
