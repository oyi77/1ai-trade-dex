from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session

from backend.models.database import get_db
from backend.api.auth import require_admin
from backend.core.agi_orchestrator import AGIOrchestrator
from backend.core.agi_goal_engine import AGIGoalEngine
from backend.core.strategy_composer import StrategyComposer
from backend.core.knowledge_graph import KnowledgeGraph
from backend.models.kg_models import DecisionAuditLog, ExperimentRecord, KGEntity as KGEntityModel

router = APIRouter(tags=["AGI"])


@router.get("/regime")
async def get_regime(db: Session = Depends(get_db)):
    from backend.core.regime_detector import RegimeDetector
    detector = RegimeDetector()
    result = detector.detect_regime({})
    return {"regime": result.regime.value, "confidence": result.confidence}


@router.get("/goal")
async def get_goal(db: Session = Depends(get_db)):
    engine = AGIGoalEngine(session=db)
    regime = None
    try:
        from backend.core.regime_detector import RegimeDetector
        detector = RegimeDetector()
        regime = detector.detect_regime(market_data={}).regime
    except Exception:
        pass
    goal = engine.get_current_goal(regime or None)
    return {"goal": goal.value, "reason": engine._goal_reason}


@router.get("/decisions")
async def get_decisions(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    offset = (page - 1) * page_size
    query = db.query(DecisionAuditLog).order_by(DecisionAuditLog.timestamp.desc())
    total = query.count()
    records = query.offset(offset).limit(page_size).all()
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "decisions": [
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "decision_type": r.decision_type,
                "input_data": r.input_data,
                "output_data": r.output_data,
                "reasoning": r.reasoning,
            }
            for r in records
        ],
    }


@router.get("/strategies/composed")
async def list_composed_strategies(db: Session = Depends(get_db)):
    records = db.query(ExperimentRecord).all()
    return {
        "strategies": [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "blocks": r.strategy_composition.get("blocks", []) if r.strategy_composition else [],
                "shadow_pnl": r.shadow_pnl,
                "shadow_trades": r.shadow_trades,
                "shadow_win_rate": r.shadow_win_rate,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    }


@router.post("/strategies/compose")
async def compose_strategy(
    name: str = Body(...),
    blocks: list[dict[str, str]] = Body(...),
    db: Session = Depends(get_db),
):
    from backend.core.agi_types import StrategyBlock
    composer = StrategyComposer(session=db)
    block_objs = [StrategyBlock(**b) for b in blocks]
    composed = composer.compose(block_objs, name=name)
    validation = composer.validate_composition(composed)
    if not validation:
        raise HTTPException(status_code=400, detail={"errors": validation.errors})
    experiment_id = composer.register_composed(composed)
    return {"id": experiment_id, "name": composed.name, "status": composed.status}


@router.get("/experiments")
async def list_experiments(db: Session = Depends(get_db)):
    records = db.query(ExperimentRecord).all()
    return {
        "experiments": [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "promoted_at": r.promoted_at.isoformat() if r.promoted_at else None,
            }
            for r in records
        ]
    }


@router.get("/knowledge-graph")
async def query_kg(
    entity_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _kg = KnowledgeGraph(session=db)
    query = db.query(KGEntityModel)
    if entity_type:
        query = query.filter_by(entity_type=entity_type)
    entities = query.all()
    return {
        "entities": [
            {
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "properties": e.properties,
            }
            for e in entities
        ]
    }


@router.post("/emergency-stop")
async def emergency_stop(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    orchestrator = AGIOrchestrator(session=db)
    orchestrator.emergency_stop()
    return {"status": "stopped", "message": "AGI emergency stop activated"}


@router.get("/status")
async def get_status(db: Session = Depends(get_db)):
    orchestrator = AGIOrchestrator(session=db)
    status = orchestrator.get_status()
    return status.to_dict()


@router.post("/run-cycle")
async def run_cycle(db: Session = Depends(get_db)):
    orchestrator = AGIOrchestrator(session=db)
    result = await orchestrator.run_cycle()
    return result.to_dict()


@router.post("/goal/override")
async def override_goal(
    goal: str = Body(...),
    reason: str = Body(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.core.agi_types import AGIGoal
    try:
        goal_enum = AGIGoal(goal)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid goal: {goal}")
    engine = AGIGoalEngine(session=db)
    audit = engine.set_goal(goal_enum, reason)
    return {"goal": goal, "reason": reason, "timestamp": audit.timestamp.isoformat()}


@router.get("/counterfactual/summary")
async def counterfactual_summary(db: Session = Depends(get_db)):
    from backend.models.outcome_tables import BlockedSignalCounterfactual, CounterfactualInsight
    from sqlalchemy import func

    total = db.query(func.count(BlockedSignalCounterfactual.id)).scalar() or 0
    scored = db.query(func.count(BlockedSignalCounterfactual.id)).filter(
        BlockedSignalCounterfactual.scored.is_(True)
    ).scalar() or 0
    won = db.query(func.count(BlockedSignalCounterfactual.id)).filter(
        BlockedSignalCounterfactual.would_have_won.is_(True)
    ).scalar() or 0
    lost = db.query(func.count(BlockedSignalCounterfactual.id)).filter(
        BlockedSignalCounterfactual.would_have_won.is_(False)
    ).scalar() or 0
    hyp_pnl = db.query(func.sum(BlockedSignalCounterfactual.hypothetical_pnl)).filter(
        BlockedSignalCounterfactual.scored.is_(True)
    ).scalar() or 0.0
    lost_profit = db.query(func.sum(BlockedSignalCounterfactual.hypothetical_pnl)).filter(
        BlockedSignalCounterfactual.would_have_won.is_(True)
    ).scalar() or 0.0

    insights = db.query(CounterfactualInsight).order_by(
        CounterfactualInsight.lost_profit.desc()
    ).limit(20).all()

    return {
        "total_blocked_signals": total,
        "scored": scored,
        "pending_resolution": total - scored,
        "would_have_won": won,
        "would_have_lost": lost,
        "counterfactual_wr": round(won / scored, 3) if scored > 0 else None,
        "hypothetical_total_pnl": round(float(hyp_pnl), 2),
        "lost_profit_from_blocking": round(float(lost_profit), 2),
        "top_insights": [
            {
                "dimension": i.dimension,
                "value": i.dimension_value,
                "total_blocked": i.total_blocked,
                "would_win": i.total_would_win,
                "counterfactual_wr": i.counterfactual_wr,
                "hypothetical_pnl": i.hypothetical_total_pnl,
                "lost_profit": i.lost_profit,
            }
            for i in insights
        ],
    }


@router.get("/counterfactual/strategy/{strategy_name}")
async def counterfactual_strategy(strategy_name: str, db: Session = Depends(get_db)):
    from backend.ai.counterfactual_scorer import get_strategy_counterfactual_stats
    return get_strategy_counterfactual_stats(db, strategy_name)


@router.get("/counterfactual/recommendations")
async def counterfactual_recommendations(db: Session = Depends(get_db)):
    from backend.ai.counterfactual_scorer import get_risk_calibration_recommendations
    return {"recommendations": get_risk_calibration_recommendations(db)}


@router.post("/counterfactual/run")
async def counterfactual_run(db: Session = Depends(get_db)):
    from backend.ai.counterfactual_scorer import run_counterfactual_cycle
    result = await run_counterfactual_cycle(db=db)
    return result


PIPELINE_COLUMNS = [
    {"id": "backtest", "label": "Backtest", "order": 0},
    {"id": "shadow", "label": "Shadow", "order": 1},
    {"id": "paper", "label": "Paper", "order": 2},
    {"id": "live_promoted", "label": "Live", "order": 3},
    {"id": "review", "label": "Review", "order": 4},
    {"id": "retired", "label": "Retired", "order": 5},
]

STATUS_TO_COLUMN = {
    "draft": "backtest",
    "backtest": "backtest",
    "shadow": "shadow",
    "paper": "paper",
    "live_promoted": "live_promoted",
    "live_failed": "review",
    "review": "review",
    "retired": "retired",
}


def _experiment_to_card(r: ExperimentRecord) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "strategy_name": r.strategy_name,
        "status": r.status,
        "column": STATUS_TO_COLUMN.get(r.status, "backtest"),
        "backtest_passed": bool(r.backtest_passed) if r.backtest_passed else False,
        "backtest_sharpe": r.backtest_sharpe,
        "backtest_win_rate": r.backtest_win_rate,
        "shadow_trades": r.shadow_trades,
        "shadow_win_rate": r.shadow_win_rate,
        "shadow_pnl": r.shadow_pnl,
        "degradation_count": r.degradation_count or 0,
        "review_reason": r.review_reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "promoted_at": r.promoted_at.isoformat() if r.promoted_at else None,
        "retired_at": r.retired_at.isoformat() if r.retired_at else None,
    }


@router.get("/kanban")
async def kanban_board(db: Session = Depends(get_db)):
    experiments = db.query(ExperimentRecord).order_by(ExperimentRecord.created_at.desc()).all()
    cards = [_experiment_to_card(r) for r in experiments]

    columns = {}
    for col in PIPELINE_COLUMNS:
        columns[col["id"]] = {**col, "cards": []}
    for card in cards:
        col_id = card["column"]
        if col_id in columns:
            columns[col_id]["cards"].append(card)

    return {
        "columns": list(columns.values()),
        "total_experiments": len(cards),
    }


@router.post("/kanban/{experiment_id}/move")
async def kanban_move_card(
    experiment_id: int,
    target_status: str = Body(..., embed=True),
    reason: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.core.agi_types import ExperimentStatus

    valid_targets = {e.value for e in ExperimentStatus}
    if target_status not in valid_targets:
        raise HTTPException(status_code=400, detail=f"Invalid status: {target_status}")

    exp = db.query(ExperimentRecord).filter_by(id=experiment_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")

    old_status = exp.status
    exp.status = target_status

    if target_status == "retired":
        exp.retired_at = datetime.now(timezone.utc)
    elif target_status in ("paper", "live_promoted"):
        exp.promoted_at = datetime.now(timezone.utc)
    elif target_status == "review" and reason:
        exp.review_reason = reason

    db.commit()
    return {
        "id": str(exp.id),
        "old_status": old_status,
        "new_status": target_status,
        "card": _experiment_to_card(exp),
    }
