import axios from 'axios'
import { getCsrfToken, getLegacyApiKey } from '../utils/auth'

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

export function getAdminApiKey(): string {
  // API key stored in httpOnly cookie — not accessible to JavaScript
  // Use CSRF token from sessionStorage instead (retrieved from cookie-based login)
  return getCsrfToken()
}

export function setAdminApiKey(key: string) {
  // Deprecated: API key is now stored in httpOnly cookie by backend.
  // This function is kept for backward compatibility but does nothing.
  // Call loginWithCookie(key) from utils/auth instead.
  // API key stored in httpOnly cookie — not accessible to JavaScript
  void key
  console.warn('[DEPRECATED] setAdminApiKey() no longer stores API key in localStorage. Use loginWithCookie() instead.')
}

