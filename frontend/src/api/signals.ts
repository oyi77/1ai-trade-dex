
import { api } from './core'

export interface SignalConfig {
  approval_mode: 'manual' | 'auto_approve' | 'auto_deny'
  min_confidence: number
  notification_duration_ms: number
}

export async function fetchSignalConfig(): Promise<SignalConfig> {
  const { data } = await api.get('/signal-config')
  return data
}

// ── AI Suggest ────────────────────────────────────────────────────────────────

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

// ============================================================================
// PE-011 Phase 2 endpoints — auto-trader pending approvals
// ============================================================================

export interface PendingApproval {
  id: number
  market_id: string
  direction: string
  size: number
  confidence: number
  signal_data: Record<string, unknown> | null
  status: string
  created_at: string | null
}

export async function fetchPendingApprovals(): Promise<PendingApproval[]> {
  const { data } = await api.get<PendingApproval[]>('/auto-trader/pending')
  return data
}

