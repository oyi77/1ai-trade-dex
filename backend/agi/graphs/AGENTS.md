<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# agi/graphs

## Purpose
Predefined directed acyclic graph (DAG) definitions for AGI pipeline orchestration. Each graph wires specific AGI nodes into a dependency-ordered execution pipeline.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Defines `MARKET_ANALYSIS_GRAPH`, `STRATEGY_EVOLUTION_GRAPH`, `FORENSICS_GRAPH`; exports `register_default_graphs()` |
| `forensics_graph.py` | Forensics graph definition (stub) |
| `market_analysis_graph.py` | Market analysis graph definition (stub) |
| `strategy_evolution_graph.py` | Strategy evolution graph definition (stub) |

## For AI Agents

### Working In This Directory
- Graphs are `GraphDefinition` dataclasses with `name`, `nodes` (list of node names), and `edges` (list of tuples)
- All node names must exist in `node_registry` at registration time or `ValueError` is raised
- Use `register_default_graphs(engine)` to register all three built-in graphs at once
- The stub files are legacy; the canonical definitions are in `__init__.py`

### Common Patterns
- Register all graphs: `engine = register_default_graphs()`
- Execute a graph: `state = await engine.execute_graph("market_analysis", initial_state)`

## Dependencies

### Internal
- `backend.agi.graph_engine` — `GraphEngine`, `GraphDefinition`
- `backend.agi.node_registry` — validates node existence
