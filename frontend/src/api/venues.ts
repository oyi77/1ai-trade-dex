
import { api } from './core'

export interface PluginStatus {
  name: string
  enabled: boolean
  version: string
  last_updated: string
  status: 'healthy' | 'warning' | 'error'
  error_message?: string
  metrics?: {
    requests_total: number
    requests_success: number
    requests_failed: number
    avg_latency_ms: number
  }
}

export interface PluginStatusResponse {
  plugins: PluginStatus[]
}

export async function fetchPluginStatus(): Promise<PluginStatusResponse> {
  const { data } = await api.get<PluginStatusResponse>('/agi/plugins/status')
  return data
}

// ── Venue Monitor ────────────────────────────────────────────────────────────

export interface VenueMetric {
  name: string
  value: number | string
  trend?: 'up' | 'down' | 'neutral'
  change?: number
}

export interface VenueStatus {
  venue: string
  connected: boolean
  last_seen: string
  metrics: VenueMetric[]
  status: 'healthy' | 'warning' | 'error'
  latency_ms: number
  issues?: string[]
}

export interface VenueDataResponse {
  venues: VenueStatus[]
}

export async function fetchVenueData(): Promise<VenueDataResponse> {
  const { data } = await api.get<VenueDataResponse>('/agi/venue/status')
  return data
}

// ── AGI Sandbox ──────────────────────────────────────────────────────────────

