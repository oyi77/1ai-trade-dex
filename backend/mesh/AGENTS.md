<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# mesh

## Purpose
Mesh network coordination layer for multi-instance PolyEdge deployments. Handles node registration, health monitoring, learning propagation between instances, and distributed auditing. Enables strategy insights and risk data to flow across mesh nodes.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker; exports MeshNode, MeshRegistry |
| `base.py` | Base types: `MeshNode` dataclass (node_id, endpoint, status, last_heartbeat), `MeshMessage` protocol |
| `registry.py` | `MeshRegistry` — in-memory node registry; add/remove nodes; query by status; TTL-based stale node eviction |
| `mesh.py` | `MeshCoordinator` — message routing between nodes; broadcast strategy updates, risk alerts, learning payloads |
| `health.py` | `MeshHealthMonitor` — periodic ping of registered nodes; track latency, uptime; mark nodes unhealthy after timeout |
| `learning.py` | `MeshLearningSync` — propagate trained model weights, strategy parameter updates, and calibration data across mesh |
| `auditor.py` | `MeshAuditor` — verify consistency of trade state, position data, and bankroll across nodes; flag discrepancies |

## For AI Agents

### Working In This Directory
- Mesh is optional — single-instance deployments don't need it; check `MESH_ENABLED` env var
- Node identity derived from `MESH_NODE_ID` (default: hostname)
- All inter-node communication is HTTP-based (no custom protocol)
- Learning sync uses eventual consistency — conflicts resolved by timestamp (last-write-wins)
- Auditor runs on a configurable interval; results logged to `MeshAuditLog` table

### Common Patterns
```python
from backend.mesh.registry import MeshRegistry
registry = MeshRegistry()
registry.register(MeshNode(node_id="node-1", endpoint="http://10.0.1.2:8000"))
alive_nodes = registry.healthy_nodes()
```

## Dependencies

### Internal
- `backend.config` — `MESH_ENABLED`, `MESH_NODE_ID`, `MESH_PEERS`, `MESH_HEALTH_INTERVAL_SECONDS`
- `backend.core.event_bus` — mesh events published to local event bus

### External
- `httpx` — inter-node HTTP calls
