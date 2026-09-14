import type {
  KanbanBoard, KanbanCard,
} from '../types'
import { api, adminApi } from './core'

export async function fetchKanbanBoard(): Promise<KanbanBoard> {
  const { data } = await api.get<KanbanBoard>('/agi/kanban')
  return data
}

export async function moveKanbanCard(experimentId: number, targetStatus: string, reason?: string): Promise<{ id: string; old_status: string; new_status: string; card: KanbanCard }> {
  const { data } = await adminApi.post(`/agi/kanban/${experimentId}/move`, { target_status: targetStatus, reason: reason ?? null })
  return data
}

// ── Plugin System ────────────────────────────────────────────────────────────

