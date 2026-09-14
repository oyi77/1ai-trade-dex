import { api, adminApi } from './client'

// ── AGI API contract types (shapes mirror backend/api/agi_routes.py) ──

export interface RegimeEntry {
  regime: string
  confidence: number
  timestamp: string
}

export interface RegimeStatus {
  regime: string
  confidence?: number
  history?: RegimeEntry[]
}

export interface GoalPerformance {
  metric: string
  value: number
  target: number
}

export interface GoalStatus {
  goal: string
  reason?: string
  set_at?: string
  performance?: GoalPerformance | null
}

export interface DecisionEntry {
  timestamp: string | null
  agent_name: string | null
  decision_type: string
  confidence: number | null
  input_data: Record<string, unknown> | null
  output_data: Record<string, unknown> | null
  reasoning: string | null
}

export interface DecisionsPage {
  page: number
  page_size: number
  total: number
  decisions: DecisionEntry[]
}

export interface StrategyBlock {
  signal_source: string
  filter: string
  position_sizer: string
  risk_rule: string
  exit_rule: string
}

export interface ComposedStrategy {
  id: string
  name: string
  status: string
  blocks: StrategyBlock[]
  shadow_pnl: number | null
  shadow_trades: number | null
  shadow_win_rate: number | null
  created_at: string | null
}

/** Result of POST /agi/run-cycle (orchestrator CycleResult.to_dict()). */
export interface ExperimentResult {
  actions_taken: number
  errors?: string[]
  decisions_recorded?: number
  trades_attempted?: number
  trades_placed?: number
  markets_scanned?: number
  cycle_duration_ms?: number
}
export interface AGIStatus {
  regime: string
  goal: string
  health: string
  emergency_stop: boolean
  allocations?: Record<string, number>
  last_cycle?: string
}

export async function fetchAGIStatus(): Promise<AGIStatus> {
  const { data } = await api.get<AGIStatus>('/agi/status')
  return data
}

export async function toggleAI(enable: boolean): Promise<{ status: string; enabled: boolean }> {
  const { data } = await adminApi.post('/agi/toggle', { enabled: enable })
  return data
}

export interface Proposal {
  id: string
  title: string
  description: string
  status: string
  created_at: string
}

export async function fetchProposals(params?: Record<string, string | number>): Promise<Proposal[]> {
  const { data } = await api.get('/agi/proposals', { params })
  return data
}

export async function approveProposal(id: string): Promise<{ status: string; id: string }> {
  const { data } = await adminApi.post(`/agi/proposals/${id}/approve`)
  return data
}

export interface Evolution {
  id: string
  description: string
  status: string
  created_at: string
  metrics?: Record<string, number>
}

export async function fetchEvolutions(params?: Record<string, string | number>): Promise<Evolution[]> {
  const { data } = await api.get('/agi/evolutions', { params })
  return data
}

export async function fetchAISuggest(): Promise<{
  status: string
  suggestions: Record<string, number | null>
  analysis: Record<string, unknown>
  ai_provider: string
  raw_response?: string
}> {
  const { data } = await api.get('/admin/ai/suggest')
  return data
}

export interface KanbanBoard {
  columns: Array<{
    id: string
    title: string
    cards: KanbanCard[]
  }>
}

export interface KanbanCard {
  id: number
  title: string
  status: string
  priority: string
  experiment_id?: number
}

export async function fetchKanbanBoard(): Promise<KanbanBoard> {
  const { data } = await api.get<KanbanBoard>('/agi/kanban')
  return data
}

export async function moveKanbanCard(experimentId: number, targetStatus: string, reason?: string): Promise<{ id: string; old_status: string; new_status: string; card: KanbanCard }> {
  const { data } = await adminApi.post(`/agi/kanban/${experimentId}/move`, { target_status: targetStatus, reason: reason ?? null })
  return data
}

export interface SandboxScenario {
  name: string
  description: string
}

export interface SandboxValidationResult {
  run_id: string
  timestamp: string
  scenario: string
  status: 'pending' | 'validating' | 'completed' | 'failed'
  result?: {
    success: boolean
    message?: string
    errors?: string[]
    warnings?: string[]
    metrics?: {
      validation_time_ms: number
      lines_of_code: number
      gate_passed: number
      total_gates: number
    }
  }
}

export interface SandboxResponse {
  scenarios: SandboxScenario[]
  results: SandboxValidationResult[]
}

export async function fetchSandboxScenarios(): Promise<SandboxResponse> {
  const { data } = await api.get<SandboxResponse>('/agi/sandbox/scenarios')
  return data
}

export async function fetchSandboxResults(): Promise<SandboxResponse> {
  const { data } = await api.get<SandboxResponse>('/agi/sandbox/results')
  return data
}

export interface AGIGraphNode {
  id: string
  label: string
  type: string
  status: string
  data?: any
}

export interface AGIGraphEdge {
  source: string
  target: string
  label?: string
}

export interface AGIGraph {
  name: string
  nodes: AGIGraphNode[]
  edges: AGIGraphEdge[]
}

export interface AGIRunResult {
  run_id: string
  graph_name: string
  timestamp: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: {
    success: boolean
    data?: any
    errors?: string[]
  }
}

export interface AGIGraphsResponse {
  graphs: AGIGraph[]
}

export interface AGIRunResultsResponse {
  results: AGIRunResult[]
}

export async function fetchAGIGraphs(): Promise<AGIGraphsResponse> {
  const { data } = await api.get<AGIGraphsResponse>('/agi/graphs')
  return data
}

export async function fetchAGIRunResult(): Promise<AGIRunResultsResponse> {
  const { data } = await api.get<AGIRunResultsResponse>('/agi/graphs/runs')
  return data
}

// ── Aggregated AGI API surface ────────────────────────────────────────────

export const agiAPI = {
  getStatus: fetchAGIStatus,

  getRegime: async (): Promise<RegimeStatus> => {
    const { data } = await api.get<RegimeStatus>('/agi/regime')
    return data
  },

  getGoal: async (): Promise<GoalStatus> => {
    const { data } = await api.get<GoalStatus>('/agi/goal')
    return data
  },

  getDecisions: async (page = 1, pageSize = 10): Promise<DecisionsPage> => {
    const { data } = await api.get<DecisionsPage>('/agi/decisions', {
      params: { page, page_size: pageSize },
    })
    return data
  },

  getComposedStrategies: async (): Promise<ComposedStrategy[]> => {
    const { data } = await api.get<{ strategies: ComposedStrategy[] }>(
      '/agi/strategies/composed',
    )
    return data.strategies
  },

  composeStrategy: async (
    name: string,
    blocks: StrategyBlock[],
  ): Promise<{ id: string | number; name: string; status: string }> => {
    const { data } = await api.post('/agi/strategies/compose', { name, blocks })
    return data
  },

  runCycle: async (): Promise<ExperimentResult> => {
    const { data } = await api.post<ExperimentResult>('/agi/run-cycle')
    return data
  },

  emergencyStop: async (): Promise<{ status: string }> => {
    const { data } = await adminApi.post('/agi/emergency-stop')
    return data
  },

  overrideGoal: async (
    goal: string,
    reason: string,
  ): Promise<{ status: string; goal: string }> => {
    const { data } = await adminApi.post('/agi/goal/override', { goal, reason })
    return data
  },
}
