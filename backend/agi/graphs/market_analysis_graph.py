"""Market analysis graph - Regime detection → Knowledge Graph → Goal engine pipeline."""
from backend.agi.graph_engine import GraphDefinition


MARKET_ANALYSIS_GRAPH = GraphDefinition(
    name="market_analysis",
    nodes=["regime_detector", "knowledge_graph", "goal_engine"],
    edges=[
        ("regime_detector", "knowledge_graph"),
        ("regime_detector", "goal_engine"),
    ],
)


def register(engine) -> None:
    engine.add_graph(MARKET_ANALYSIS_GRAPH)
