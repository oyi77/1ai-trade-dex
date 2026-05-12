"""AGI Graph API router for PolyEdge plugin system."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from backend.api.auth import require_admin
from backend.agi.graph_engine import GraphEngine, GraphDefinition
from backend.agi.agent_state import AgentState
from backend.agi.graphs import (
    MARKET_ANALYSIS_GRAPH,
    STRATEGY_EVOLUTION_GRAPH,
    FORENSICS_GRAPH,
    register_default_graphs,
)

router = APIRouter(tags=["AGI Graphs"])


@router.get("/graphs")
async def list_graphs(_: Session = Depends(require_admin)):
    """List all available AGI graph definitions."""
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


@router.get("/graphs/{name}")
async def get_graph(name: str, _: Session = Depends(require_admin)):
    """Get details for a specific AGI graph."""
    graphs = {
        MARKET_ANALYSIS_GRAPH.name: MARKET_ANALYSIS_GRAPH,
        STRATEGY_EVOLUTION_GRAPH.name: STRATEGY_EVOLUTION_GRAPH,
        FORENSICS_GRAPH.name: FORENSICS_GRAPH,
    }

    if name not in graphs:
        raise HTTPException(status_code=404, detail=f"Graph '{name}' not found")

    graph = graphs[name]
    return {
        "name": graph.name,
        "nodes": graph.nodes,
        "edges": [{"from": src, "to": dst} for src, dst in graph.edges],
    }


@router.post("/graphs/{name}/run")
async def run_graph(
    name: str,
    initial_data: Optional[dict] = None,
    is_sandbox: bool = False,
    _: Session = Depends(require_admin),
):
    """Execute an AGI graph with initial data."""
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
            run_id=f"api-run-{name}",
            graph_name=name,
            data=initial_data or {},
            is_sandbox=is_sandbox,
        )
        result = await engine.execute_graph(name, initial_state)
        return {
            "run_id": f"api-run-{name}",
            "graph_name": name,
            "result": result.data,
            "errors": result.errors,
            "is_sandbox": result.is_sandbox,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graphs/{name}/results/{run_id}")
async def get_graph_execution_result(
    name: str, run_id: str, _: Session = Depends(require_admin)
):
    """Get execution results for a specific graph run."""
    graphs = {
        MARKET_ANALYSIS_GRAPH.name: MARKET_ANALYSIS_GRAPH,
        STRATEGY_EVOLUTION_GRAPH.name: STRATEGY_EVOLUTION_GRAPH,
        FORENSICS_GRAPH.name: FORENSICS_GRAPH,
    }

    if name not in graphs:
        raise HTTPException(status_code=404, detail=f"Graph '{name}' not found")

    engine = GraphEngine()
    initial_state = AgentState(
        run_id=run_id,
        graph_name=name,
        data={},
        is_sandbox=False,
    )

    try:
        result = await engine.execute_graph(name, initial_state)
        return {
            "run_id": run_id,
            "graph_name": name,
            "result": result.data,
            "errors": result.errors,
            "is_sandbox": result.is_sandbox,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/graphs/register")
async def register_graph(
    graph_def: GraphDefinition, _: Session = Depends(require_admin)
):
    """Register a new custom graph definition."""
    try:
        engine = GraphEngine()
        engine.add_graph(graph_def)
        return {"status": "registered", "name": graph_def.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/graphs/defaults")
async def get_default_graphs(_: Session = Depends(require_admin)):
    """Get default registered graphs."""
    engine = register_default_graphs()
    return {
        "default_graphs": [
            {"name": g.name, "nodes": g.nodes, "edges": g.edges}
            for g in engine.graphs.values()
        ]
    }
