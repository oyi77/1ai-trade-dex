export type { RegimeStatus, GoalStatus, DecisionEntry, ComposedStrategy, ExperimentResult, AGIStatus } from './client'
import { api, adminApi } from './client'

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
