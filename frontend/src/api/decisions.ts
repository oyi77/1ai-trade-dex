import { api } from './client'

export interface DecisionLogRow {
  id: number
  strategy: string
  market_ticker: string
  decision: string
  confidence: number | null
  reason: string | null
  outcome: string | null
  created_at: string | null
  signal_data?: Record<string, unknown> | null
}

export interface DecisionLogDetail extends DecisionLogRow {
  signal_data: Record<string, unknown> | null
}

export async function fetchDecisions(params?: Record<string, string | number>): Promise<{ items: DecisionLogRow[]; total: number }> {
  const { data } = await api.get('/decisions', { params })
  return data
}

export async function fetchDecisionDetail(id: number): Promise<DecisionLogDetail> {
  const { data } = await api.get(`/decisions/${id}`)
  return data
}

export async function fetchDecision(id: number): Promise<DecisionLogDetail> {
  return fetchDecisionDetail(id)
}

export const API_BASE = (import.meta as any).env?.VITE_API_URL || ''

export function decisionsExportUrl(params?: Record<string, string>): string {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return `${API_BASE}/api/v1/decisions/export${qs}`
}

export function exportDecisions(params?: Record<string, string>): string {
  return decisionsExportUrl(params)
}
