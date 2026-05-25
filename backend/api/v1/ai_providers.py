"""FastAPI router for AI provider management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.auth import require_admin
from backend.ai.llm_router import llm_router

router = APIRouter(tags=["AI Providers"])


@router.get("/providers")
async def list_providers(_: Session = Depends(require_admin)):
    """List all available AI providers."""
    return {
        "providers": [
            {
                "name": m["name"],
                "display_name": m["display_name"],
                "version": m["version"],
                "tags": m.get("tags", []),
                "cost_per_1k_tokens_usd": m.get("cost_per_1k_tokens_usd", 0),
                "max_tokens": m.get("max_tokens", 0),
                "supports_streaming": m.get("supports_streaming", False),
                "supports_tool_use": m.get("supports_tool_use", False),
            }
            for m in llm_router.list_available()
        ]
    }


@router.get("/providers/{name}")
async def get_provider(name: str, _: Session = Depends(require_admin)):
    """Get details for a specific AI provider."""
    info = llm_router.get_provider_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"AI provider '{name}' not found")
    return info


@router.post("/providers/{name}/enable")
async def enable_provider(name: str, _: Session = Depends(require_admin)):
    """Enable an AI provider."""
    info = llm_router.get_provider_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"AI provider '{name}' not found")
    llm_router.set_enabled(name, True)
    return {"status": "enabled", "name": name}


@router.post("/providers/{name}/disable")
async def disable_provider(name: str, _: Session = Depends(require_admin)):
    """Disable an AI provider."""
    info = llm_router.get_provider_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"AI provider '{name}' not found")
    llm_router.set_enabled(name, False)
    return {"status": "disabled", "name": name}
