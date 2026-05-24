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
  let originalLocation: Location;

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    originalLocation = window.location;
    // @ts-ignore
    delete window.location;
    window.location = { ...originalLocation } as any;
  })

  afterEach(() => {
    vi.restoreAllMocks()
    window.location = originalLocation;
    vi.unstubAllEnvs();
    vi.resetModules();
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

  describe('getWsUrl', () => {
    it('uses window.location for ws when API_BASE is empty (http)', async () => {
      vi.stubEnv('VITE_API_URL', '');
      window.location.protocol = 'http:';
      window.location.host = 'localhost:3000';

      const { getWsUrl } = await import('../api');
      expect(getWsUrl('/ws-test')).toBe('ws://localhost:3000/ws-test');
    });

    it('uses window.location for wss when API_BASE is empty and protocol is https', async () => {
      vi.stubEnv('VITE_API_URL', '');
      window.location.protocol = 'https:';
      window.location.host = 'example.com';

      const { getWsUrl } = await import('../api');
      expect(getWsUrl('/ws-test')).toBe('wss://example.com/ws-test');
    });

    it('uses API_BASE when available (http -> ws)', async () => {
      vi.stubEnv('VITE_API_URL', 'http://api.example.com');
      window.location.hostname = 'example.com'; // ensures getApiBase doesn't clear it for local mismatch

      const { getWsUrl } = await import('../api');
      expect(getWsUrl('/ws-test')).toBe('ws://api.example.com/ws-test');
    });

    it('uses API_BASE when available (https -> wss)', async () => {
      vi.stubEnv('VITE_API_URL', 'https://api.example.com');
      window.location.hostname = 'example.com';

      const { getWsUrl } = await import('../api');
      expect(getWsUrl('/ws-test')).toBe('wss://api.example.com/ws-test');
    });

    it('handles paths missing a leading slash gracefully with window.location fallback', async () => {
      vi.stubEnv('VITE_API_URL', '');
      window.location.protocol = 'https:';
      window.location.host = 'example.com';

      const { getWsUrl } = await import('../api');
      expect(getWsUrl('ws-test')).toBe('wss://example.com/ws-test');
    });

    it('handles paths missing a leading slash gracefully with API_BASE', async () => {
      vi.stubEnv('VITE_API_URL', 'https://api.example.com');
      window.location.hostname = 'example.com';

      const { getWsUrl } = await import('../api');
      expect(getWsUrl('ws-test')).toBe('wss://api.example.com/ws-test');
    });
  })
})
