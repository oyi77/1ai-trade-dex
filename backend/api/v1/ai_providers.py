"""FastAPI router for AI provider management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.auth import require_admin
from backend.ai.provider_registry import provider_registry
from backend.core.plugin_errors import PluginNotFound

router = APIRouter(tags=["AI Providers"])


@router.get("/providers")
async def list_providers(_: Session = Depends(require_admin)):
    """List all available AI providers."""
    return {
        "providers": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "version": m.version,
                "tags": m.tags,
                "cost_per_1k_tokens_usd": getattr(m, "cost_per_1k_tokens_usd", 0),
                "max_tokens": getattr(m, "max_tokens", 0),
                "supports_streaming": getattr(m, "supports_streaming", False),
                "supports_tool_use": getattr(m, "supports_tool_use", False),
            }
            for m in provider_registry.list_available()
        ]
    }


@router.get("/providers/{name}")
async def get_provider(name: str, _: Session = Depends(require_admin)):
    """Get details for a specific AI provider."""
    try:
        provider = provider_registry.get(name)
        manifest = provider.manifest()
        return {
            "name": manifest.name,
            "display_name": manifest.display_name,
            "version": manifest.version,
            "description": manifest.__doc__ or "",
            "tags": manifest.tags,
            "required_env_vars": manifest.required_env_vars,
            "enabled": provider_registry._enabled.get(name, False),
            "healthy": provider_registry._health_status.get(name, False),
        }
    except PluginNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/providers/{name}/enable")
async def enable_provider(name: str, _: Session = Depends(require_admin)):
    """Enable an AI provider."""
    try:
        provider_registry.set_enabled(name, True)
        return {"status": "enabled", "name": name}
    except PluginNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/providers/{name}/disable")
async def disable_provider(name: str, _: Session = Depends(require_admin)):
    """Disable an AI provider."""
    try:
        provider_registry.set_enabled(name, False)
        return {"status": "disabled", "name": name}
    except PluginNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))