"""Knowledge graph AGI node - wraps existing KnowledgeGraph."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class KnowledgeGraphNode(BaseAGINode):
    """Queries the knowledge graph and adds results to agent state."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="knowledge_graph",
            version="1.0.0",
            description="Queries the knowledge graph for relevant entities and relations",
            input_keys=["query"],
            output_keys=["entities", "relations"],
            requires_db=True,
            tags=["knowledge", "query"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.knowledge_graph import KnowledgeGraph

        query = state.get("query", "")
        if not query:
            return state.with_error(self.manifest().name, ValueError("No query provided"))

        try:
            kg = KnowledgeGraph()
            entities = kg.query_entities(query)
            relations = kg.query_relations(query)
            return state.evolve(
                data={
                    "entities": entities,
                    "relations": relations,
                    "kg_query": query,
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)
