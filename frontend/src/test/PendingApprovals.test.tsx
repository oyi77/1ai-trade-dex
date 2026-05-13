import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PendingApprovals from '../pages/PendingApprovals'

vi.mock('../api', () => ({
  fetchPendingApprovals: vi.fn().mockResolvedValue([]),
  approvePendingTrade: vi.fn().mockResolvedValue({ id: 1, status: 'approved' }),
  rejectPendingTrade: vi.fn().mockResolvedValue({ id: 1, status: 'rejected' }),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return Wrapper
}

describe('PendingApprovals page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the empty state when no items pending', async () => {
    render(<PendingApprovals />, { wrapper: createWrapper() })
    await waitFor(() => {
      expect(screen.getByText(/No pending approvals/i)).toBeInTheDocument()
    })
  })

  it('renders rows and triggers approve when present', async () => {
    const mod = await import('../api')
    vi.mocked(mod.fetchPendingApprovals).mockResolvedValueOnce([
      {
        id: 7,
        market_id: 'BTC-MAR-2026',
        direction: 'BUY',
        size: 50,
        confidence: 0.62,
        signal_data: null,
        status: 'pending',
        created_at: '2026-04-07T14:00:00',
      },
    ])
    render(<PendingApprovals />, { wrapper: createWrapper() })
    await waitFor(() => {
      expect(screen.getByText('BTC-MAR-2026')).toBeInTheDocument()
    })
    expect(screen.getAllByText('62.0%').length).toBeGreaterThan(0)

    const approveBtn = screen.getByRole('button', { name: 'Approve' })
    fireEvent.click(approveBtn)
    await waitFor(() => {
      expect(vi.mocked(mod.approvePendingTrade)).toHaveBeenCalledWith(7)
    })
  })

  it('shows an error message on fetch failure', async () => {
    const mod = await import('../api')
    vi.mocked(mod.fetchPendingApprovals).mockRejectedValueOnce(new Error('boom'))
    render(<PendingApprovals />, { wrapper: createWrapper() })
    await waitFor(() => {
      expect(screen.getByText(/boom/i)).toBeInTheDocument()
    })
  })
})
