"""Brain Graph API - Visualize AI decision flow.

Provides REST endpoints and WebSocket streams for the Brain Graph visualization:
- GET /api/brain/graph - Returns node/edge data structure
- GET /api/brain/debate/{id} - Returns debate transcript for a decision
- GET /api/brain/learning - Returns learning feedback loops

WebSocket endpoint registered in main.py as /ws/brain for real-time updates.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.models.database import get_db, DecisionLog, SystemSettings

logger = logging.getLogger("trading_bot.brain_api")

router = APIRouter(prefix="/brain", tags=["brain"])


# --- Response Models ---

class GraphNode(BaseModel):
    """A node in the brain graph."""
    id: str
    type: str  # "signal_source", "ai_agent", "strategy", "executor"
    label: str
    status: str  # "active", "idle", "processing"
    metadata: Dict[str, Any] = {}


class GraphEdge(BaseModel):
    """An edge connecting two nodes."""
    from_node: str
    to_node: str
    weight: float  # 0.0-1.0
    active: bool
    label: Optional[str] = None


class BrainGraphResponse(BaseModel):
    """Complete brain graph structure."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    timestamp: str


class DebateTranscript(BaseModel):
    """Debate transcript for a single decision."""
    decision_id: int
    market_question: str
    market_price: float
    bull_arguments: List[Dict[str, Any]]
    bear_arguments: List[Dict[str, Any]]
    judge_synthesis: Dict[str, Any]
    signal_votes: List[Dict[str, Any]]
    consensus_probability: float
    confidence: float
    rounds_completed: int
    latency_ms: float
    timestamp: str


class LearningFeedback(BaseModel):
    """Learning feedback loop data."""
    proposal_id: int
    strategy_name: str
    change_type: str
    change_details: Dict[str, Any]
    expected_impact: str
    status: str  # "pending", "approved", "rejected"
    created_at: str
    executed_at: Optional[str] = None


# --- Helper Functions ---

def _build_graph_structure(db: Session) -> Dict[str, Any]:
    """Build the brain graph node/edge structure.

    Returns:
        Dictionary with 'nodes' and 'edges' lists
    """
    nodes = []
    edges = []

    # --- Signal Sources ---
    nodes.append(GraphNode(
        id="mirofish",
        type="signal_source",
        label="MiroFish",
        status="active",
        metadata={"description": "External signal aggregator"}
    ))

    # --- Strategies (9 total) ---
    strategies = [
        "btc_momentum", "btc_oracle", "weather_emos", "copy_trader",
        "market_maker", "kalshi_arb", "bond_scanner", "whale_pnl_tracker",
        "realtime_scanner"
    ]

    for strategy in strategies:
        nodes.append(GraphNode(
            id=strategy,
            type="strategy",
            label=strategy.replace("_", " ").title(),
            status="idle",
            metadata={"strategy_name": strategy}
        ))

    # --- Signal Aggregator ---
    nodes.append(GraphNode(
        id="signal_aggregator",
        type="processor",
        label="Signal Aggregator",
        status="active",
        metadata={"description": "Aggregates signals from all strategies"}
    ))

    # --- AI Agents (Bull/Bear/Judge) ---
    nodes.append(GraphNode(
        id="bull_agent",
        type="ai_agent",
        label="Bull Agent",
        status="idle",
        metadata={"role": "debate_agent", "stance": "bull"}
    ))

    nodes.append(GraphNode(
        id="bear_agent",
        type="ai_agent",
        label="Bear Agent",
        status="idle",
        metadata={"role": "debate_agent", "stance": "bear"}
    ))

    nodes.append(GraphNode(
        id="judge_agent",
        type="ai_agent",
        label="Judge Agent",
        status="idle",
        metadata={"role": "judge"}
    ))

    # --- Risk Manager ---
    nodes.append(GraphNode(
        id="risk_manager",
        type="processor",
        label="Risk Manager",
        status="active",
        metadata={"description": "Validates position sizing and risk limits"}
    ))

    # --- Trade Executor ---
    nodes.append(GraphNode(
        id="trade_executor",
        type="executor",
        label="Trade Executor",
        status="active",
        metadata={"description": "Executes approved trades"}
    ))

    # --- Trade Analyzer ---
    nodes.append(GraphNode(
        id="trade_analyzer",
        type="processor",
        label="Trade Analyzer",
        status="active",
        metadata={"description": "Analyzes trade outcomes"}
    ))

    # --- Proposal Generator ---
    nodes.append(GraphNode(
        id="proposal_generator",
        type="ai_agent",
        label="Proposal Generator",
        status="idle",
        metadata={"description": "Generates strategy improvement proposals"}
    ))

    # --- Edges (Data Flow) ---

    # MiroFish → Signal Aggregator
    edges.append(GraphEdge(
        from_node="mirofish",
        to_node="signal_aggregator",
        weight=0.8,
        active=True,
        label="external_signals"
    ))

    # Strategies → Signal Aggregator
    for strategy in strategies:
        edges.append(GraphEdge(
            from_node=strategy,
            to_node="signal_aggregator",
            weight=0.7,
            active=False,
            label="strategy_signal"
        ))

    # Signal Aggregator → Bull/Bear Agents
    edges.append(GraphEdge(
        from_node="signal_aggregator",
        to_node="bull_agent",
        weight=0.9,
        active=False,
        label="market_context"
    ))

    edges.append(GraphEdge(
        from_node="signal_aggregator",
        to_node="bear_agent",
        weight=0.9,
        active=False,
        label="market_context"
    ))

    # Bull/Bear → Judge
    edges.append(GraphEdge(
        from_node="bull_agent",
        to_node="judge_agent",
        weight=0.85,
        active=False,
        label="bull_argument"
    ))

    edges.append(GraphEdge(
        from_node="bear_agent",
        to_node="judge_agent",
        weight=0.85,
        active=False,
        label="bear_argument"
    ))

    # Judge → Risk Manager
    edges.append(GraphEdge(
        from_node="judge_agent",
        to_node="risk_manager",
        weight=0.95,
        active=False,
        label="consensus_decision"
    ))

    # Risk Manager → Trade Executor
    edges.append(GraphEdge(
        from_node="risk_manager",
        to_node="trade_executor",
        weight=0.9,
        active=False,
        label="approved_trade"
    ))

    # Trade Executor → Trade Analyzer
    edges.append(GraphEdge(
        from_node="trade_executor",
        to_node="trade_analyzer",
        weight=1.0,
        active=False,
        label="executed_trade"
    ))

    # Trade Analyzer → Proposal Generator (feedback loop)
    edges.append(GraphEdge(
        from_node="trade_analyzer",
        to_node="proposal_generator",
        weight=0.7,
        active=False,
        label="performance_analysis"
    ))

    # Proposal Generator → Strategies (feedback loop)
    for strategy in strategies[:3]:  # Show feedback to first 3 strategies
        edges.append(GraphEdge(
            from_node="proposal_generator",
            to_node=strategy,
            weight=0.6,
            active=False,
            label="strategy_update"
        ))

    return {"nodes": nodes, "edges": edges}


# --- Endpoints ---

@router.get("/status")
async def get_brain_status(db: Session = Depends(get_db)):
    """Get brain status with strategy states for REST polling fallback."""
    from backend.models.database import StrategyConfig
    strategies = []
    for config in db.query(StrategyConfig).all():
        strategies.append({
            "id": config.strategy_name,
            "name": config.strategy_name,
            "label": config.strategy_name.replace("_", " ").title(),
            "type": "signal",
            "enabled": config.enabled if config.enabled is not None else True,
        })

    mirofish_setting = db.query(SystemSettings).filter(SystemSettings.key == "mirofish_enabled").first()
    mirofish_enabled = str(mirofish_setting.value).lower() in ("true", "1", "yes") if mirofish_setting else False

    pipeline_nodes = [
        {"id": "bull_agent", "name": "bull_agent", "label": "Bull Agent", "type": "ai", "enabled": True},
        {"id": "bear_agent", "name": "bear_agent", "label": "Bear Agent", "type": "ai", "enabled": True},
        {"id": "judge_agent", "name": "judge_agent", "label": "Judge Agent", "type": "ai", "enabled": True},
        {"id": "risk_manager", "name": "risk_manager", "label": "Risk Manager", "type": "analysis", "enabled": True},
        {"id": "trade_analyzer", "name": "trade_analyzer", "label": "Trade Analyzer", "type": "analysis", "enabled": True},
        {"id": "trade_executor", "name": "trade_executor", "label": "Trade Executor", "type": "execution", "enabled": True},
        {"id": "proposal_gen", "name": "proposal_gen", "label": "Proposal Gen", "type": "analysis", "enabled": True},
    ]

    return {
        "strategies": strategies + pipeline_nodes,
        "mirofish_enabled": mirofish_enabled,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/graph", response_model=BrainGraphResponse)
async def get_brain_graph(
    db: Session = Depends(get_db),
):
    """Get the brain graph structure with nodes and edges.

    Returns the complete decision flow graph showing:
    - Signal sources (MiroFish, strategies)
    - AI agents (Bull, Bear, Judge)
    - Processing nodes (Risk Manager, Trade Executor, Trade Analyzer)
    - Learning feedback (Proposal Generator)

    Edge weights represent confidence/importance (0.0-1.0).
    Edge 'active' status shows if data is currently flowing.
    """
    graph_data = _build_graph_structure(db)

    return BrainGraphResponse(
        nodes=graph_data["nodes"],
        edges=graph_data["edges"],
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@router.get("/debate/{decision_id}", response_model=DebateTranscript)
async def get_debate_transcript(
    decision_id: int,
    db: Session = Depends(get_db),
):
    """Get the full debate transcript for a decision.

    Args:
        decision_id: DecisionLog ID

    Returns:
        Complete debate transcript with Bull/Bear arguments and Judge synthesis

    Raises:
        404: Decision not found or no debate data available
    """
    decision = db.query(DecisionLog).filter(DecisionLog.id == decision_id).first()

    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    if not decision.signal_data:
        raise HTTPException(status_code=404, detail="No debate data available for this decision")

    # Extract debate transcript from signal_data
    signal_data = decision.signal_data
    debate_data = signal_data.get("debate_transcript", {})

    if not debate_data:
        raise HTTPException(status_code=404, detail="No debate transcript in signal data")

    return DebateTranscript(
        decision_id=decision.id,
        market_question=signal_data.get("market_question", "Unknown"),
        market_price=signal_data.get("market_price", 0.0),
        bull_arguments=debate_data.get("bull_arguments", []),
        bear_arguments=debate_data.get("bear_arguments", []),
        judge_synthesis=debate_data.get("judge", {}),
        signal_votes=debate_data.get("signal_votes", []),
        consensus_probability=debate_data.get("judge", {}).get("consensus_probability", 0.0),
        confidence=debate_data.get("judge", {}).get("confidence", 0.0),
        rounds_completed=debate_data.get("rounds_completed", 0),
        latency_ms=debate_data.get("latency_ms", 0.0),
        timestamp=decision.timestamp.isoformat() if decision.timestamp else datetime.now(timezone.utc).isoformat()
    )


@router.get("/learning", response_model=List[LearningFeedback])
async def get_learning_feedback(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get recent learning feedback proposals.

    Args:
        limit: Maximum number of proposals to return (default: 20)

    Returns:
        List of strategy improvement proposals with approval status
    """
    from backend.models.database import StrategyProposal

    proposals = (
        db.query(StrategyProposal)
        .order_by(StrategyProposal.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for p in proposals:
        result.append(LearningFeedback(
            proposal_id=p.id,
            strategy_name=p.strategy_name,
            change_type="parameter_adjustment",  # Default type
            change_details=p.change_details or {},
            expected_impact=p.expected_impact or "Unknown",
            status=p.admin_decision or "pending",
            created_at=p.created_at.isoformat() if p.created_at else datetime.now(timezone.utc).isoformat(),
            executed_at=p.executed_at.isoformat() if p.executed_at else None
        ))

    return result
