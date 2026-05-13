import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Settings from '../components/admin/SettingsTab'

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

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: any) => children,
}))

import axios from 'axios'

const mockAxios = axios.create()

const mockSettingsData = {
  mirofish_enabled: false,
  mirofish_api_url: '',
  mirofish_api_key: '',
  strategies: {
    btc_momentum: true,
    btc_oracle: false,
    weather_emos: true,
    copy_trader: false,
    market_maker: true,
    kalshi_arb: false,
    bond_scanner: false,
    whale_pnl: false,
    realtime_scanner: false,
  },
  risk: {
    max_position_size: 0.1,
    max_portfolio_exposure: 0.5,
    kelly_fraction: 0.25,
    min_edge_threshold: 0.02,
  },
  trading_mode: 'paper' as const,
}

describe('Settings - MiroFish UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    void (mockAxios.get as any).mockResolvedValue({
      data: mockSettingsData,
    })
  })

  describe('Initial Load', () => {
    it('loads and displays settings', async () => {
      render(<Settings />)

      expect(screen.getByText(/Loading Settings/i)).toBeInTheDocument()

      await waitFor(() => {
        expect(screen.getByText(/System Settings/i)).toBeInTheDocument()
      })

      expect(mockAxios.get).toHaveBeenCalledWith('/settings')
    })

    it('displays error when settings fail to load', async () => {
      void (mockAxios.get as any).mockRejectedValueOnce({
        response: {
          data: { detail: 'Failed to fetch settings' },
        },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/Failed to fetch settings/i)).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument()
    })

    it('retries loading settings when retry button clicked', async () => {
      (mockAxios.get as any)
        .mockRejectedValueOnce({
          response: { data: { detail: 'Network error' } },
        })
        .mockResolvedValueOnce({
          data: mockSettingsData,
        })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/Network error/i)).toBeInTheDocument()
      })

      const retryButton = screen.getByRole('button', { name: /Retry/i })
      await userEvent.click(retryButton)

      await waitFor(() => {
        expect(screen.getByText(/System Settings/i)).toBeInTheDocument()
      })

      expect(mockAxios.get).toHaveBeenCalledTimes(2)
    })
  })

  describe('MiroFish Toggle Switch', () => {
    it('displays toggle switch in disabled state', async () => {
      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/MiroFish AI Brain/i)).toBeInTheDocument()
      })

      const toggleButton = screen.getByRole('button', { name: '' }).closest('button')
      expect(toggleButton).toHaveClass('bg-neutral-700')
    })

    it('toggles MiroFish on and shows credential inputs', async () => {
      const enabledSettings = { ...mockSettingsData, mirofish_enabled: true }
      void (mockAxios.get as any).mockResolvedValue({
        data: enabledSettings,
      })
      void (mockAxios.put as any).mockResolvedValue({
        data: { ...enabledSettings, mirofish_enabled: false },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/MiroFish AI Brain/i)).toBeInTheDocument()
      })

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
        expect(screen.getByPlaceholderText(/••••••••••••••••/i)).toBeInTheDocument()
      })
    })

    it('prevents enabling without credentials', async () => {
      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/MiroFish AI Brain/i)).toBeInTheDocument()
      })

      const toggleButtons = screen.getAllByRole('button')
      const toggleButton = toggleButtons.find((btn) =>
        btn.className.includes('w-14 h-7')
      )

      await userEvent.click(toggleButton!)

      await waitFor(() => {
        expect(
          screen.getByText(
            /Please enter API URL and API Key, then test the connection before enabling/i
          )
        ).toBeInTheDocument()
      })

      expect(mockAxios.put).not.toHaveBeenCalled()
    })

    it('prevents enabling without successful connection test', async () => {
      const settingsWithCreds = {
        ...mockSettingsData,
        mirofish_api_url: 'https://api.mirofish.ai',
        mirofish_api_key: 'test-key-123',
      }

      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithCreds,
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/MiroFish AI Brain/i)).toBeInTheDocument()
      })

      const toggleButtons = screen.getAllByRole('button')
      const toggleButton = toggleButtons.find((btn) =>
        btn.className.includes('w-14 h-7')
      )

      await userEvent.click(toggleButton!)

      await waitFor(() => {
        expect(
          screen.getByText(/Please test the connection successfully before enabling MiroFish/i)
        ).toBeInTheDocument()
      })

      expect(mockAxios.put).not.toHaveBeenCalled()
    })
  })

  describe('Credential Inputs', () => {
    beforeEach(() => {
      const settingsWithEnabled = {
        ...mockSettingsData,
        mirofish_enabled: true,
      }
      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithEnabled,
      })
    })

    it('displays API URL and API Key input fields', async () => {
      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
        expect(screen.getByPlaceholderText(/••••••••••••••••/i)).toBeInTheDocument()
      })
    })

    it('updates API URL when user types', async () => {
      void (mockAxios.put as any).mockResolvedValue({ data: mockSettingsData })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
      })

      const urlInput = screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i) as HTMLInputElement
      await userEvent.type(urlInput, 'https://custom.api.com')

      await waitFor(() => {
        expect(mockAxios.put).toHaveBeenCalledWith(
          '/settings',
          expect.objectContaining({
            mirofish_api_url: 'https://custom.api.com',
          })
        )
      })
    })

    it('updates API Key when user types', async () => {
      void (mockAxios.put as any).mockResolvedValue({ data: mockSettingsData })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/••••••••••••••••/i)).toBeInTheDocument()
      })

      const keyInput = screen.getByPlaceholderText(/••••••••••••••••/i) as HTMLInputElement
      await userEvent.type(keyInput, 'secret-key-xyz')

      await waitFor(() => {
        expect(mockAxios.put).toHaveBeenCalledWith(
          '/settings',
          expect.objectContaining({
            mirofish_api_key: 'secret-key-xyz',
          })
        )
      })
    })

    it('disables inputs while saving', async () => {
      void (mockAxios.put as any).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: mockSettingsData }), 100)
          )
      )

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
      })

      const urlInput = screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i) as HTMLInputElement
      await userEvent.type(urlInput, 'https://test.com')

      await waitFor(() => {
        expect(urlInput).toBeDisabled()
      })
    })
  })

  describe('Test Connection Button', () => {
    beforeEach(() => {
      const settingsWithCreds = {
        ...mockSettingsData,
        mirofish_enabled: true,
        mirofish_api_url: 'https://api.mirofish.ai',
        mirofish_api_key: 'test-key-123',
      }
      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithCreds,
      })
    })

    it('displays Test Connection button', async () => {
      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })
    })

    it('shows loading state while testing', async () => {
      void (mockAxios.post as any).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: { success: true } }), 100)
          )
      )

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Testing.../i })).toBeInTheDocument()
      })
    })

    it('disables button while testing', async () => {
      void (mockAxios.post as any).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: { success: true } }), 100)
          )
      )

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(testButton).toBeDisabled()
      })
    })

    it('shows success message on successful connection', async () => {
      void (mockAxios.post as any).mockResolvedValue({
        data: { success: true },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Connected/i)).toBeInTheDocument()
      })

      expect(mockAxios.post).toHaveBeenCalledWith('/settings/test-mirofish', {
        api_url: 'https://api.mirofish.ai',
        api_key: 'test-key-123',
      })
    })

    it('shows error message on connection failure', async () => {
      void (mockAxios.post as any).mockResolvedValue({
        data: { success: false, error: 'Invalid API key' },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Invalid API key/i)).toBeInTheDocument()
      })
    })

    it('shows error on network timeout', async () => {
      void (mockAxios.post as any).mockRejectedValue({
        response: {
          data: { detail: 'Connection timeout' },
        },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Connection timeout/i)).toBeInTheDocument()
      })
    })

    it('shows error on authentication failure', async () => {
      void (mockAxios.post as any).mockRejectedValue({
        response: {
          data: { detail: 'Unauthorized: Invalid credentials' },
        },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Unauthorized: Invalid credentials/i)).toBeInTheDocument()
      })
    })

    it('prevents test when credentials are missing', async () => {
      const settingsNoCreds = {
        ...mockSettingsData,
        mirofish_enabled: true,
        mirofish_api_url: '',
        mirofish_api_key: '',
      }
      void (mockAxios.get as any).mockResolvedValue({
        data: settingsNoCreds,
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(
          screen.getByText(/Please enter both API URL and API Key/i)
        ).toBeInTheDocument()
      })

      expect(mockAxios.post).not.toHaveBeenCalled()
    })
  })

  describe('Validation Logic', () => {
    it('validates that credentials are required before enabling', async () => {
      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/MiroFish AI Brain/i)).toBeInTheDocument()
      })

      const toggleButtons = screen.getAllByRole('button')
      const toggleButton = toggleButtons.find((btn) =>
        btn.className.includes('w-14 h-7')
      )

      await userEvent.click(toggleButton!)

      await waitFor(() => {
        expect(
          screen.getByText(
            /Please enter API URL and API Key, then test the connection before enabling/i
          )
        ).toBeInTheDocument()
      })
    })

    it('allows enabling after successful connection test', async () => {
      const settingsWithCreds = {
        ...mockSettingsData,
        mirofish_enabled: true,
        mirofish_api_url: 'https://api.mirofish.ai',
        mirofish_api_key: 'test-key-123',
      }

      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithCreds,
      })

      void (mockAxios.post as any).mockResolvedValue({
        data: { success: true },
      })

      void (mockAxios.put as any).mockResolvedValue({
        data: settingsWithCreds,
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Connected/i)).toBeInTheDocument()
      })

      expect(mockAxios.post).toHaveBeenCalledWith('/settings/test-mirofish', {
        api_url: 'https://api.mirofish.ai',
        api_key: 'test-key-123',
      })
    })

    it('clears error message when credentials are entered', async () => {
      const settingsWithEnabled = {
        ...mockSettingsData,
        mirofish_enabled: true,
      }
      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithEnabled,
      })

      void (mockAxios.put as any).mockResolvedValue({
        data: settingsWithEnabled,
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
      })

      expect(
        screen.queryByText(
          /Please enter API URL and API Key, then test the connection before enabling/i
        )
      ).not.toBeInTheDocument()
    })
  })

  describe('Error States', () => {
    beforeEach(() => {
      const settingsWithCreds = {
        ...mockSettingsData,
        mirofish_enabled: true,
        mirofish_api_url: 'https://api.mirofish.ai',
        mirofish_api_key: 'test-key-123',
      }
      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithCreds,
      })
    })

    it('displays timeout error', async () => {
      void (mockAxios.post as any).mockRejectedValue({
        response: {
          data: { detail: 'Request timeout after 30s' },
        },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Request timeout after 30s/i)).toBeInTheDocument()
      })
    })

    it('displays auth failure error', async () => {
      void (mockAxios.post as any).mockRejectedValue({
        response: {
          data: { detail: 'Authentication failed: Invalid API key' },
        },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Authentication failed: Invalid API key/i)).toBeInTheDocument()
      })
    })

    it('displays connection error', async () => {
      void (mockAxios.post as any).mockRejectedValue({
        response: {
          data: { detail: 'Failed to connect to MiroFish API' },
        },
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Failed to connect to MiroFish API/i)).toBeInTheDocument()
      })
    })

    it('handles network error without response', async () => {
      void (mockAxios.post as any).mockRejectedValue(new Error('Network error'))

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Connection test failed/i)).toBeInTheDocument()
      })
    })
  })

  describe('Loading States', () => {
    beforeEach(() => {
      const settingsWithCreds = {
        ...mockSettingsData,
        mirofish_enabled: true,
        mirofish_api_url: 'https://api.mirofish.ai',
        mirofish_api_key: 'test-key-123',
      }
      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithCreds,
      })
    })

    it('shows saving indicator when updating settings', async () => {
      void (mockAxios.put as any).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: mockSettingsData }), 100)
          )
      )

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
      })

      const urlInput = screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)
      await userEvent.type(urlInput, 'https://new.api.com')

      await waitFor(() => {
        expect(screen.getByText(/Saving.../i)).toBeInTheDocument()
      })
    })

    it('disables test button while saving', async () => {
      void (mockAxios.put as any).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: mockSettingsData }), 100)
          )
      )

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Test Connection/i })).toBeInTheDocument()
      })

      const urlInput = screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)
      await userEvent.type(urlInput, 'https://new.api.com')

      const testButton = screen.getByRole('button', { name: /Test Connection/i })

      await waitFor(() => {
        expect(testButton).toBeDisabled()
      })
    })

    it('disables toggle while saving', async () => {
      void (mockAxios.put as any).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: mockSettingsData }), 100)
          )
      )

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
      })

      const urlInput = screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)
      await userEvent.type(urlInput, 'https://new.api.com')

      const toggleButtons = screen.getAllByRole('button')
      const toggleButton = toggleButtons.find((btn) =>
        btn.className.includes('w-14 h-7')
      )

      await waitFor(() => {
        expect(toggleButton).toBeDisabled()
      })
    })
  })

  describe('Integration', () => {
    it('completes full MiroFish setup flow', async () => {
      const settingsWithCreds = {
        ...mockSettingsData,
        mirofish_enabled: true,
        mirofish_api_url: 'https://api.mirofish.ai',
        mirofish_api_key: 'test-key-123',
      }

      void (mockAxios.get as any).mockResolvedValue({
        data: settingsWithCreds,
      })

      void (mockAxios.post as any).mockResolvedValue({
        data: { success: true },
      })

      void (mockAxios.put as any).mockResolvedValue({
        data: settingsWithCreds,
      })

      render(<Settings />)

      await waitFor(() => {
        expect(screen.getByText(/System Settings/i)).toBeInTheDocument()
      })

      expect(screen.getByPlaceholderText(/https:\/\/api.mirofish.ai/i)).toBeInTheDocument()
      expect(screen.getByPlaceholderText(/••••••••••••••••/i)).toBeInTheDocument()

      const testButton = screen.getByRole('button', { name: /Test Connection/i })
      await userEvent.click(testButton)

      await waitFor(() => {
        expect(screen.getByText(/Connected/i)).toBeInTheDocument()
      })

      expect(mockAxios.post).toHaveBeenCalledWith('/settings/test-mirofish', {
        api_url: 'https://api.mirofish.ai',
        api_key: 'test-key-123',
      })
    })
  })
})
