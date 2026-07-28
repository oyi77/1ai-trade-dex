import { getCsrfToken } from '../utils/auth'

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
