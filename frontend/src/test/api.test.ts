import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

// Mock axios before importing api
vi.mock('axios', () => {
  const instance = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }
  return {
    default: {
      create: vi.fn(() => instance),
    },
  }
})

import { getAdminApiKey, setAdminApiKey, decisionsExportUrl, fetchTradeAttempts, fetchTradeAttemptSummary } from '../api'
import axios from 'axios'

const mockAxiosInstance = (axios.create as unknown as ReturnType<typeof vi.fn>).mock.results[0].value

describe('api utility functions', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('getAdminApiKey', () => {
    it('returns empty string when not set', () => {
      expect(getAdminApiKey()).toBe('')
    })

    it('returns csrf token from sessionStorage when set', () => {
      // getAdminApiKey() now delegates to getCsrfToken() which reads sessionStorage
      sessionStorage.setItem('admin_csrf_token', 'csrf-token-123')
      expect(getAdminApiKey()).toBe('csrf-token-123')
    })
  })

  describe('setAdminApiKey', () => {
    it('logs deprecation warning and is a no-op', () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      setAdminApiKey('abc123')
      expect(warnSpy).toHaveBeenCalledWith(
        '[DEPRECATED] setAdminApiKey() no longer stores API key in localStorage. Use loginWithCookie() instead.'
      )
      expect(localStorage.getItem('adminApiKey')).toBeNull()
    })

    it('does not remove existing localStorage key', () => {
      localStorage.setItem('adminApiKey', 'existing-key')
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      setAdminApiKey('')
      expect(localStorage.getItem('adminApiKey')).toBe('existing-key')
      expect(warnSpy).toHaveBeenCalled()
    })
  })

  describe('decisionsExportUrl', () => {
    it('returns base URL with no params', () => {
      const url = decisionsExportUrl()
      expect(url).toBe('/api/v1/decisions/export')
    })

    it('returns URL with query params', () => {
      const url = decisionsExportUrl({ strategy: 'momentum', decision: 'BUY' })
      expect(url).toContain('/api/v1/decisions/export?')
      expect(url).toContain('strategy=momentum')
      expect(url).toContain('decision=BUY')
    })

    it('returns URL with single query param', () => {
      const url = decisionsExportUrl({ format: 'csv' })
      expect(url).toBe('/api/v1/decisions/export?format=csv')
    })
  })

  describe('trade attempt endpoints', () => {
    it('fetches trade attempts with filters', async () => {
      mockAxiosInstance.get.mockResolvedValueOnce({ data: { items: [], total: 0 } })

      await fetchTradeAttempts({ mode: 'paper', status: 'REJECTED' })

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/trade-attempts', {
        params: { mode: 'paper', status: 'REJECTED' },
      })
    })

    it('fetches trade attempt summary', async () => {
      mockAxiosInstance.get.mockResolvedValueOnce({ data: { total: 0, executed: 0, blocked: 0 } })

      await fetchTradeAttemptSummary({ mode: 'live' })

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/trade-attempts/summary', {
        params: { mode: 'live' },
      })
    })
  })
})
