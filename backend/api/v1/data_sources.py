"""Data source API router for PolyEdge plugin system."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.auth import require_admin
from backend.data.source_registry import source_registry
from backend.core.plugin_errors import PluginNotFound

router = APIRouter(tags=["Data Sources"])


@router.get("/sources")
async def list_sources(_: Session = Depends(require_admin)):
    """List all available data sources."""
    return {
        "sources": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "version": m.version,
                "data_types": [dt.value for dt in m.data_types],
                "supports_streaming": m.supports_streaming,
                "supports_backfill": m.supports_backfill,
                "is_live": m.is_live,
                "rate_limit_per_minute": m.rate_limit_per_minute,
                "tags": m.tags,
            }
            for m in source_registry.list_available()
        ]
    }


@router.get("/sources/{name}")
async def get_source(name: str, _: Session = Depends(require_admin)):
    """Get details for a specific data source."""
    try:
        source = source_registry.get(name)
        manifest = source.manifest()
        return {
            "name": manifest.name,
            "display_name": manifest.display_name,
            "version": manifest.version,
            "data_types": [dt.value for dt in manifest.data_types],
            "supports_streaming": manifest.supports_streaming,
            "supports_backfill": manifest.supports_backfill,
            "is_live": manifest.is_live,
            "required_env_vars": manifest.required_env_vars,
            "enabled": source_registry._enabled.get(name, False),
            "healthy": source_registry._health_status.get(name, False),
        }
    except PluginNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sources/{name}/enable")
async def enable_source(name: str, _: Session = Depends(require_admin)):
    """Enable a data source."""
    try:
        source_registry.set_enabled(name, True)
        return {"status": "enabled", "name": name}
    except PluginNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sources/{name}/disable")
async def disable_source(name: str, _: Session = Depends(require_admin)):
    """Disable a data source."""
    try:
        source_registry.set_enabled(name, False)
        return {"status": "disabled", "name": name}
    except PluginNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
