<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# agi/nodes

## Purpose
Concrete AGI node implementations. Each node is a pluggable processing unit that receives an `AgentState`, performs domain-specific logic, and returns an updated state. Nodes are auto-discovered by the `NodeRegistry`.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Empty (auto-discovery handles registration) |
| `auto_improve_node.py` | Applies auto-improvement actions based on forensics results |
| `codebase_scanner_node.py` | Scans codebase for complexity, dead code, and improvement opportunities |
| `evolution_node.py` | Runs genome evolution and strategy promotion |
| `forensics_node.py` | Analyzes trade outcomes to identify failure patterns |
| `goal_engine_node.py` | Manages and prioritizes AGI goals |
| `improvement_planner_node.py` | Plans concrete improvement tasks from scan results |
| `knowledge_graph_node.py` | Updates the knowledge graph with new learnings |
| `model_calibration_node.py` | Calibrates ML model parameters from recent data |
| `regime_detector_node.py` | Detects market regime changes (trending, ranging, volatile) |
| `self_healing_node.py` | Detects and proposes fixes for system failures |
| `strategy_composer_node.py` | Composes new strategy variants from existing components |
| `strategy_synthesizer_node.py` | Synthesizes entirely new strategy concepts |

## For AI Agents

### Working In This Directory
- Every node subclasses `BaseAGINode` from `backend.agi.base_node`
- Must implement `manifest() -> NodeManifest` (classmethod) and `execute(state) -> state` (async)
- Node names in `manifest()` must be unique — they are the registry keys
- Declare `input_keys` and `output_keys` in the manifest for graph validation
- Set `requires_db=True` or `requires_live_data=True` if the node needs those — graph engine skips them in sandbox mode
- Nodes are auto-discovered on import of `backend.agi` — just placing a file here with a valid `BaseAGINode` subclass is enough

### Testing Requirements
- Test each node in isolation with a mock `AgentState`
- Verify `can_execute()` returns False when required input keys are missing
- Run: `pytest backend/agi/tests/ -v`

### Common Patterns
- Create a node: subclass `BaseAGINode`, implement `manifest()` and `execute(state)`
- Check executability: `node.can_execute(state)` — checks all `input_keys` exist in `state.data`

## Dependencies

### Internal
- `backend.agi.base_node` — `BaseAGINode`, `NodeManifest`
- `backend.agi.agent_state` — `AgentState`
- `backend.agi.node_registry` — auto-registers nodes on import
