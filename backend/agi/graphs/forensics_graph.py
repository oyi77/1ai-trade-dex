from backend.agi.graph_engine import GraphDefinition


FORENSICS_GRAPH = GraphDefinition(
    name="forensics",
    nodes=["forensics", "knowledge_graph", "auto_improve"],
    edges=[
        ("forensics", "knowledge_graph"),
        ("forensics", "auto_improve"),
    ],
)


def register(engine) -> None:
    engine.add_graph(FORENSICS_GRAPH)
