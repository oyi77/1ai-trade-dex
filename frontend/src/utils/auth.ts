/**
 * Cookie-based auth utilities for admin API.
 *
 * Flow:
 * 1. Login: POST /api/v1/admin/auth/login with admin_key → httpOnly cookie set + CSRF token returned
 * 2. All adminApi requests: cookie sent automatically by browser; CSRF token in X-CSRF-Token header
 * 3. Logout: POST /api/v1/admin/auth/logout → cookie cleared
 */
const CSRF_STORAGE_KEY = 'admin_csrf_token'
let cachedCsrfToken: string | null = null
export function getCsrfToken(): string {
  if (cachedCsrfToken) return cachedCsrfToken
  const stored = sessionStorage.getItem(CSRF_STORAGE_KEY)
  if (stored) {
    cachedCsrfToken = stored
    return stored
  }
  return ''
}
export function setCsrfToken(token: string) {
  cachedCsrfToken = token
  if (token) {
    sessionStorage.setItem(CSRF_STORAGE_KEY, token)
  } else {
    sessionStorage.removeItem(CSRF_STORAGE_KEY)
  }
}
export function clearCsrfToken() {
  cachedCsrfToken = null
  sessionStorage.removeItem(CSRF_STORAGE_KEY)
}
export function isLoggedIn(): boolean {
  return getCsrfToken().length > 0
}
export interface LoginResponse {
  csrf_token: string
  message: string
}
export async function loginWithCookie(adminKey: string): Promise<LoginResponse> {
  const API_BASE = import.meta.env.VITE_API_URL || ''
  const res = await fetch(`${API_BASE}/api/v1/admin/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ admin_key: adminKey }),
    credentials: 'include',
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: 'Login failed' }))
    throw new Error(detail.detail || 'Login failed')
  }
  const data: LoginResponse = await res.json()
  setCsrfToken(data.csrf_token)
  return data
}
export async function logoutWithCookie(): Promise<void> {
  const API_BASE = import.meta.env.VITE_API_URL || ''
  const csrf = getCsrfToken()
  await fetch(`${API_BASE}/api/v1/admin/auth/logout`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrf },
    credentials: 'include',
  }).catch(() => {})
  clearCsrfToken()
  // API key stored in httpOnly cookie — not accessible to JavaScript
}
/**
 * Legacy fallback: no longer stores key in localStorage.
 * API key is now securely stored in httpOnly cookie by backend.
 * @deprecated Use loginWithCookie() instead
 */
export function setLegacyApiKey(key: string) {
  console.warn('[DEPRECATED] setLegacyApiKey() no longer stores API key in localStorage. Use loginWithCookie() instead.')
  void key
  // This function is kept for backward compatibility but does nothing.
  // API key stored in httpOnly cookie — not accessible to JavaScript
}
/**
 * Legacy fallback: no longer retrieves from localStorage.
 * Returns empty string as API key is stored securely in httpOnly cookie.
 * @deprecated Use getCsrfToken() instead for authenticated requests
 */
export function getLegacyApiKey(): string {
  return ''
}
