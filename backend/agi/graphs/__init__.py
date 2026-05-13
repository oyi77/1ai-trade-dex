"""AGI graph definitions."""
from backend.agi.graph_engine import GraphEngine, GraphDefinition


# Market Analysis Graph: Regime → Knowledge Graph → Goal Engine
MARKET_ANALYSIS_GRAPH = GraphDefinition(
    name="market_analysis",
    nodes=["regime_detector", "knowledge_graph", "goal_engine"],
    edges=[
        ("regime_detector", "knowledge_graph"),
        ("regime_detector", "goal_engine"),
    ],
)

# Strategy Evolution Graph: Synthesizer → Sandbox → Promoter
STRATEGY_EVOLUTION_GRAPH = GraphDefinition(
    name="strategy_evolution",
    nodes=["strategy_synthesizer", "model_calibration", "evolution"],
    edges=[
        ("strategy_synthesizer", "model_calibration"),
        ("model_calibration", "evolution"),
    ],
)

# Forensics Graph: Forensics → Knowledge Graph → Auto Improve
FORENSICS_GRAPH = GraphDefinition(
    name="forensics",
    nodes=["forensics", "knowledge_graph", "auto_improve"],
    edges=[
        ("forensics", "knowledge_graph"),
        ("forensics", "auto_improve"),
    ],
)


def register_default_graphs(engine: GraphEngine = None) -> None:
    """Register all default graphs with the engine."""
    eng = engine or GraphEngine()
    eng.add_graph(MARKET_ANALYSIS_GRAPH)
    eng.add_graph(STRATEGY_EVOLUTION_GRAPH)
    eng.add_graph(FORENSICS_GRAPH)
    return eng
