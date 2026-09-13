"""Carved verbatim out of ``backend/api/settings.py`` — statements moved, no logic changed."""

from ._settings_test_mirofish import (
    CreateRiskProfileRequest,
)

from .settings import (
    Depends,
    Session,
    get_db,
    require_admin,
    router,
)

from . import settings as _facade

@router.post("/risk/profile")
async def create_risk_profile(
    body: CreateRiskProfileRequest,
    _: None = Depends(require_admin),
):
    from backend.core.risk.risk_profiles import create_profile, RiskProfile

    try:
        profile = RiskProfile(
            name=body.name,
            display_name=body.display_name,
            kelly_fraction=body.kelly_fraction,
            min_edge_threshold=body.min_edge_threshold,
            max_trade_size=body.max_trade_size,
            max_position_fraction=body.max_position_fraction,
            max_total_exposure_fraction=body.max_total_exposure_fraction,
            daily_loss_limit=body.daily_loss_limit,
            daily_drawdown_limit_pct=body.daily_drawdown_limit_pct,
            weekly_drawdown_limit_pct=body.weekly_drawdown_limit_pct,
            slippage_tolerance=body.slippage_tolerance,
            auto_approve_min_confidence=body.auto_approve_min_confidence,
            max_concentration_pct=body.max_concentration_pct,
            max_correlated_exposure_pct=body.max_correlated_exposure_pct,
            longshot_no_bias_weight=body.longshot_no_bias_weight,
        )
        created = create_profile(profile)
        return {"status": "ok", "profile": _facade._profile_to_response(created).model_dump()}
    except ValueError as e:
        raise _facade.HTTPException(status_code=409, detail=str(e))
@router.delete("/risk/profile/{name}")
async def delete_risk_profile(
    name: str,
    _: None = Depends(require_admin),
):
    from backend.core.risk.risk_profiles import delete_profile

    deleted = delete_profile(name)
    if not deleted:
        raise _facade.HTTPException(
            status_code=400,
            detail=f"Cannot delete preset profile or profile not found: {name}",
        )
    return {"status": "ok", "deleted": name}
@router.get("/mirofish/signals")
async def get_mirofish_signals(
    market: str = "polymarket",
    question: str = "",
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Get AI-powered trading signals — routes to external MiroFish or built-in debate engine.

    Behaviour controlled by MIROFISH_ENABLED and MIROFISH_API_URL in settings:
    - If MIROFISH_ENABLED=true and MIROFISH_API_URL points external → calls external MiroFish API
    - Otherwise → uses built-in Bull/Bear/Judge debate engine (Groq/Claude LLMs)
    """
    import json as _json
    from backend.config import settings as app

    if app.MIROFISH_ENABLED and app.MIROFISH_API_URL:
        try:
            from backend.ai.mirofish_client import MiroFishClient

            client = MiroFishClient()
            raw_signals = await client.fetch_signals(market=market, question=question)
            if raw_signals:
                signals = [
                    {
                        "market_id": s.market_id,
                        "market_question": getattr(s, "market_question", ""),
                        "prediction": s.prediction,
                        "confidence": s.confidence,
                        "reasoning": s.reasoning,
                        "source": s.source,
                        "generated_at": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        "signal_id": f"mirofish_{hash(s.market_id) % 100000:05d}",
                    }
                    for s in raw_signals
                ]
                return {
                    "signals": signals,
                    "count": len(signals),
                    "source": "external_mirofish",
                }
        except Exception as e:
            _facade.logger.warning(
                f"External MiroFish failed, falling back to debate engine: {e}"
            )

    from backend.ai.debate_engine import run_debate
    from backend.data.gamma import fetch_markets

    try:
        markets = await fetch_markets(limit=5)
        signals = []
        for m in markets[:1]:
            question = m.get("question", "Unknown market")
            prices_str = m.get("outcomePrices", "[]")
            try:
                prices = (
                    _json.loads(prices_str)
                    if isinstance(prices_str, str)
                    else prices_str
                )
                yes_price = float(prices[0]) if prices else 0.5
            except (_json.JSONDecodeError, IndexError, ValueError, TypeError):
                yes_price = 0.5
            volume = float(m.get("volume", 0) or m.get("liquidity", 0) or 0)

            result = await run_debate(
                question=question,
                market_price=yes_price,
                volume=volume,
                category=m.get("category", ""),
                max_rounds=1,
            )
            if result:
                bull_reasoning = (
                    result.bull_arguments[0].reasoning if result.bull_arguments else ""
                )
                bear_reasoning = (
                    result.bear_arguments[0].reasoning if result.bear_arguments else ""
                )
                signals.append(
                    {
                        "market_id": str(m.get("id", "")),
                        "market_question": question,
                        "market_type": m.get("category", "crypto"),
                        "prediction": result.consensus_probability,
                        "confidence": result.confidence,
                        "edge": abs(result.consensus_probability - yes_price),
                        "fair_value": result.consensus_probability,
                        "current_price": yes_price,
                        "reasoning": result.reasoning,
                        "bull_args": bull_reasoning,
                        "bear_args": bear_reasoning,
                        "sources": result.data_sources or ["debate_engine"],
                        "generated_at": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        "signal_id": f"debate_{hash(question) % 100000:05d}",
                        "latency_ms": result.latency_ms,
                        "rounds": result.rounds_completed,
                    }
                )
            else:
                signals.append(
                    {
                        "market_id": str(m.get("id", "")),
                        "market_question": question,
                        "market_type": m.get("category", "crypto"),
                        "prediction": yes_price,
                        "confidence": 0.3,
                        "edge": 0.0,
                        "fair_value": yes_price,
                        "current_price": yes_price,
                        "reasoning": "Debate engine returned no result",
                        "sources": ["debate_engine"],
                        "generated_at": _facade.datetime.now(_facade.timezone.utc).isoformat(),
                        "signal_id": f"nodata_{hash(question) % 100000:05d}",
                    }
                )

        return {"signals": signals, "count": len(signals), "source": "debate_engine"}
    except Exception as e:
        _facade.logger.error(f"MiroFish signals failed: {e}")
        return {"signals": [], "count": 0, "source": "error", "error": str(e)}
