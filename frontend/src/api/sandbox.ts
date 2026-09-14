import { api } from './core'

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

// ── AGI Graphs ───────────────────────────────────────────────────────────────

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

// --- Multi-Wallet & Copy-Trade API ---
