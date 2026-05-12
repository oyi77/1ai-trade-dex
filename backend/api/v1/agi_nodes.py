"""AGI API router for PolyEdge plugin system."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from backend.api.auth import require_admin
from backend.agi.node_registry import node_registry
from backend.agi.graph_engine import GraphEngine
from backend.agi.agent_state import AgentState

router = APIRouter(tags=["AGI Nodes"])


@router.get("/nodes")
async def list_nodes(_: Session = Depends(require_admin)):
    """List all available AGI nodes."""
    return {
        "nodes": [
            {
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "input_keys": m.input_keys,
                "output_keys": m.output_keys,
                "requires_db": m.requires_db,
                "requires_live_data": m.requires_live_data,
                "tags": m.tags,
            }
            for m in node_registry.list_all()
        ]
    }


@router.get("/nodes/{name}")
async def get_node(name: str, _: Session = Depends(require_admin)):
    """Get details for a specific AGI node."""
    try:
        node = node_registry.get(name)
        manifest = node.manifest()
        return {
            "name": manifest.name,
            "description": manifest.description,
            "version": manifest.version,
            "input_keys": manifest.input_keys,
            "output_keys": manifest.output_keys,
            "requires_db": manifest.requires_db,
            "requires_live_data": manifest.requires_live_data,
            "tags": manifest.tags,
            "enabled": node_registry._enabled.get(name, False),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/nodes/{name}/enable")
async def enable_node(name: str, _: Session = Depends(require_admin)):
    """Enable an AGI node."""
    try:
        node_registry.set_enabled(name, True)
        return {"status": "enabled", "name": name}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/nodes/{name}/disable")
async def disable_node(name: str, _: Session = Depends(require_admin)):
    """Disable an AGI node."""
    try:
        node_registry.set_enabled(name, False)
        return {"status": "disabled", "name": name}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/graphs")
async def list_graphs(_: Session = Depends(require_admin)):
    """List all available AGI graph definitions."""
    from backend.agi.graphs import MARKET_ANALYSIS_GRAPH, STRATEGY_EVOLUTION_GRAPH, FORENSICS_GRAPH

    graphs = [MARKET_ANALYSIS_GRAPH, STRATEGY_EVOLUTION_GRAPH, FORENSICS_GRAPH]
    return {
        "graphs": [
            {
                "name": g.name,
                "nodes": g.nodes,
                "edges": [{"from": src, "to": dst} for src, dst in g.edges],
            }
            for g in graphs
        ]
    }


@router.post("/graphs/{name}/run")
async def run_graph(
    name: str,
    initial_data: Optional[dict] = None,
    is_sandbox: bool = False,
    _: Session = Depends(require_admin),
):
    """Execute an AGI graph with initial data."""
    from backend.agi.graphs import MARKET_ANALYSIS_GRAPH, STRATEGY_EVOLUTION_GRAPH, FORENSICS_GRAPH

    graphs = {
        MARKET_ANALYSIS_GRAPH.name: MARKET_ANALYSIS_GRAPH,
        STRATEGY_EVOLUTION_GRAPH.name: STRATEGY_EVOLUTION_GRAPH,
        FORENSICS_GRAPH.name: FORENSICS_GRAPH,
    }

    if name not in graphs:
        raise HTTPException(status_code=404, detail=f"Graph '{name}' not found")

    try:
        engine = GraphEngine()
        initial_state = AgentState(
            run_id="api-run",
            graph_name=name,
            data=initial_data or {},
            is_sandbox=is_sandbox,
        )
        result = await engine.execute_graph(name, initial_state)
        return {
            "run_id": "api-run",
            "graph_name": name,
            "result": result.data,
            "errors": result.errors,
            "is_sandbox": result.is_sandbox,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
