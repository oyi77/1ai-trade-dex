from backend.agi.graph_engine import GraphDefinition


STRATEGY_EVOLUTION_GRAPH = GraphDefinition(
    name="strategy_evolution",
    nodes=["strategy_synthesizer", "model_calibration", "evolution"],
    edges=[
        ("strategy_synthesizer", "model_calibration"),
        ("model_calibration", "evolution"),
    ],
)


def register(engine) -> None:
    engine.add_graph(STRATEGY_EVOLUTION_GRAPH)
