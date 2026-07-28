import type { DashboardData, Signal, Trade, BotStats, BtcPrice, BtcWindow, WeatherForecast, WeatherSignal, Setting, TradeAttemptSummary, TradeAttemptsResponse, KanbanBoard, KanbanCard, JournalEntry, JournalStats, EvalReportsResponse, EvalReportDetail } from '../types'
import { getCsrfToken, getLegacyApiKey } from '../utils/auth'
import axios from 'axios'

const getApiBase = () => {
  const env = import.meta.env.VITE_API_URL
  if (env && env !== 'undefined') {
    const isEnvLocal = env.includes('localhost') || env.includes('127.0.0.1')
    const isPageLocal = window.location.hostname.includes('localhost') || window.location.hostname.includes('127.0.0.1')
    
    if (isEnvLocal && !isPageLocal) {
      return ''
    }
    return env
  }
  return ''
}
export const API_BASE = getApiBase()

const API_TIMEOUT = Number(import.meta.env.VITE_API_TIMEOUT_MS) || 15000

/**
 * Build a WebSocket URL for the given path.
 * In production with VITE_API_URL set, converts http(s) to ws(s).
 * In dev (no VITE_API_URL), uses current page host with protocol detection.
 */
export function getWsUrl(path: string): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, 'ws') + path
  }
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}${path}`
}

export const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: API_TIMEOUT,
})

export const adminApi = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: API_TIMEOUT,
})

adminApi.interceptors.request.use(config => {
  const csrf = getCsrfToken()
  if (csrf) {
    config.headers = config.headers ?? {}
    config.headers['X-CSRF-Token'] = csrf
  }
  const legacy = getLegacyApiKey()
  if (legacy && !csrf) {
    config.headers = config.headers ?? {}
    config.headers['Authorization'] = `Bearer ${legacy}`
  }
  config.withCredentials = true
  return config
})
