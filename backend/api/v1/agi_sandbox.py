"""AGI Sandbox API router."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.auth import require_admin
from backend.agi.sandbox.sandbox_manager import sandbox_manager

router = APIRouter(tags=["AGI Sandbox"])


@router.get("/scenarios")
async def list_scenarios(_: Session = Depends(require_admin)):
    """List available sandbox scenarios."""
    return {
        "scenarios": [
            {"name": "default", "description": "Default market conditions"},
            {"name": "bull_2024", "description": "Bull market scenario"},
            {"name": "bear_market", "description": "Bear market scenario"},
            {"name": "high_volatility", "description": "High volatility scenario"},
            {"name": "low_liquidity", "description": "Low liquidity scenario"},
        ]
    }


@router.post("/validate")
async def validate_strategy(
    code: str,
    scenario: str = "default",
    _: Session = Depends(require_admin),
):
    """Submit strategy code for sandbox validation (4-gate pipeline)."""
    result = await sandbox_manager.validate_strategy(code, scenario)
    return result.to_dict()


@router.post("/validate-node")
async def validate_node(
    node_name: str,
    state: dict,
    _: Session = Depends(require_admin),
):
    """Validate a single AGI node in sandbox context."""
    result = await sandbox_manager.validate_node(node_name, state)
    return result.to_dict()


@router.get("/results/{run_id}")
async def get_validation_result(run_id: str, _: Session = Depends(require_admin)):
    """Get a previous validation result by run ID."""
    result = sandbox_manager.get_result(run_id)
    if not result:
        return {"error": "Result not found"}
    return result.to_dict()


@router.get("/results")
async def list_validation_results(_: Session = Depends(require_admin)):
    """List all validation results."""
    results = sandbox_manager.list_results()
    return {"results": [r.to_dict() for r in results]}
