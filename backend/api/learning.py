from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.api.auth import require_admin
from backend.core.outcome_repository import (
    get_recent_outcomes, record_param_change
)
from backend.core.trading_calibration import TradingCalibration
from backend.core.thompson_sampler import ThompsonSampler
from backend.core.strategy_health import StrategyHealthMonitor


router = APIRouter(prefix="/learning", tags=["learning"])


class StrategyHealthResponse(BaseModel):
    strategy: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    sharpe: float
    max_drawdown: float
    brier_score: float
    psi_score: float
    status: str


class CalibrationCurveResponse(BaseModel):
    strategy: str
    predicted_probs: List[float]
    actual_frequencies: List[float]
    brier_score: float


class AllocationResponse(BaseModel):
    strategy: str
    allocation: float
    alpha: float
    beta: float


class ParamChangeRequest(BaseModel):
    strategy: str
    param_name: str
    old_value: float
    new_value: float
    auto_applied: bool
    reasoning: str


class OutcomeResponse(BaseModel):
    trade_id: int
    strategy: str
    result: str
    pnl: float
    model_probability: float


_tc = TradingCalibration()
_ts = ThompsonSampler()
_health = StrategyHealthMonitor()


@router.get("/health/{strategy}", response_model=StrategyHealthResponse)
async def get_strategy_health(strategy: str, db: Session = Depends(get_db)):
    result = _health.assess(strategy, db, readonly=True)
    return StrategyHealthResponse(**result)


@router.get("/health", response_model=List[StrategyHealthResponse])
async def get_all_strategy_health(db: Session = Depends(get_db)):
    from backend.models.database import StrategyConfig
    configs = db.query(StrategyConfig).all()
    strategies = [c.strategy_name for c in configs] if configs else ["unknown"]
    return [StrategyHealthResponse(**_health.assess(s, db, readonly=True)) for s in strategies]


@router.get("/calibration/{strategy}", response_model=CalibrationCurveResponse)
async def get_calibration(strategy: str, db: Session = Depends(get_db)):
    outcomes = get_recent_outcomes(strategy, 200, db)
    pairs = [
        (o.model_probability, 1 if o.result == "win" else 0)
        for o in outcomes
        if o.model_probability is not None and o.result in ("win", "loss")
    ]
    if not pairs:
        raise HTTPException(status_code=404, detail="No calibration data found")

    bucket_size = 0.1
    buckets: dict = {}
    for prob, actual in pairs:
        key = round(int(prob / bucket_size) * bucket_size, 1)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(actual)

    sorted_keys = sorted(buckets.keys())
    predicted = [k + bucket_size / 2 for k in sorted_keys]
    actual_freq = [sum(buckets[k]) / len(buckets[k]) for k in sorted_keys]
    brier = sum((p - a) ** 2 for p, a in pairs) / len(pairs)

    return CalibrationCurveResponse(
        strategy=strategy,
        predicted_probs=predicted,
        actual_frequencies=actual_freq,
        brier_score=brier,
    )


@router.get("/allocations", response_model=List[AllocationResponse])
async def get_allocations(db: Session = Depends(get_db)):
    from backend.models.database import StrategyConfig
    configs = db.query(StrategyConfig).filter(StrategyConfig.enabled).all()
    strategies = [c.strategy_name for c in configs] if configs else []
    if not strategies:
        return []

    allocations = _ts.allocate(strategies, total_capital=1000.0)
    result = []
    for s in strategies:
        posterior = _ts._posteriors.get(s, (1.0, 1.0))
        result.append(AllocationResponse(
            strategy=s,
            allocation=allocations.get(s, 0.0),
            alpha=posterior[0],
            beta=posterior[1],
        ))
    return result


@router.get("/outcomes/{strategy}", response_model=List[OutcomeResponse])
async def get_outcomes(strategy: str, limit: int = 50, db: Session = Depends(get_db)):
    outcomes = get_recent_outcomes(strategy, limit, db)
    return [
        OutcomeResponse(
            trade_id=o.trade_id,
            strategy=o.strategy,
            result=o.result,
            pnl=o.pnl or 0.0,
            model_probability=o.model_probability or 0.0,
        )
        for o in outcomes
    ]


@router.post("/param-change")
async def log_param_change(
    req: ParamChangeRequest,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    record_param_change(
        strategy=req.strategy,
        param=req.param_name,
        old_val=req.old_value,
        new_val=req.new_value,
        db=db,
    )
    return {"status": "recorded"}
