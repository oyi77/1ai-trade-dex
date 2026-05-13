import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ControlRoomTab } from '../components/dashboard/ControlRoomTab'

vi.mock('../api', () => ({
  fetchTradeAttempts: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  fetchTradeAttemptSummary: vi.fn().mockResolvedValue({
    total: 0,
    executed: 0,
    blocked: 0,
    execution_rate: 0,
    last_attempt_at: null,
    by_status: [],
    by_mode: [],
    top_blockers: [],
    recent_blockers: [],
  }),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function ControlRoomTestWrapper({ children }: { children: React.ReactNode }) {
    return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  }
  return ControlRoomTestWrapper
}

describe('ControlRoomTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders summary counters and blocker chips', async () => {
    const mod = await import('../api')
    vi.mocked(mod.fetchTradeAttemptSummary).mockResolvedValueOnce({
      total: 3,
      executed: 1,
      blocked: 2,
      execution_rate: 1 / 3,
      last_attempt_at: '2026-04-27T12:00:00Z',
      by_status: [],
      by_mode: [],
      top_blockers: [{ reason_code: 'REJECTED_DRAWDOWN_BREAKER', count: 2 }],
      recent_blockers: [],
    })

    render(<ControlRoomTab />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Trade Control Room')).toBeInTheDocument()
      expect(screen.getByText('REJECTED_DRAWDOWN_BREAKER: 2')).toBeInTheDocument()
    })
    expect(screen.getByText('33.3%')).toBeInTheDocument()
  })

  it('shows expandable attempt details with risk reason and AI reasoning', async () => {
    const mod = await import('../api')
    vi.mocked(mod.fetchTradeAttempts).mockResolvedValueOnce({
      total: 1,
      items: [{
        id: 1,
        attempt_id: 'attempt-1',
        correlation_id: 'corr-1',
        created_at: '2026-04-27T12:00:00Z',
        updated_at: '2026-04-27T12:00:01Z',
        strategy: 'general_scanner',
        mode: 'live',
        market_ticker: 'BTC-TEST',
        platform: 'polymarket',
        direction: 'yes',
        decision: 'BUY',
        status: 'REJECTED',
        phase: 'risk_gate',
        reason_code: 'REJECTED_DRAWDOWN_BREAKER',
        reason: 'drawdown breaker',
        confidence: 0.8,
        edge: 0.1,
        requested_size: 50,
        adjusted_size: 0,
        entry_price: 0.55,
        bankroll: 170.1,
        current_exposure: 100,
        risk_allowed: false,
        risk_reason: '24h loss exceeds limit',
        trade_id: null,
        order_id: null,
        latency_ms: 4.2,
        factors: { bankroll: 170.1, current_exposure: 100 },
        decision_data: null,
        signal_data: { reasoning: 'AI liked the edge but risk stopped it.' },
      }],
    })

    render(<ControlRoomTab />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText('BTC-TEST')).toBeInTheDocument())
    fireEvent.click(screen.getByText('BTC-TEST'))

    expect(screen.getByText('Risk: 24h loss exceeds limit')).toBeInTheDocument()
    expect(screen.getByText('AI liked the edge but risk stopped it.')).toBeInTheDocument()
  })
})
