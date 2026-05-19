import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSSEEvents } from './useSSEEvents';
import { API_BASE } from '../api';
import { ModeFilterProvider } from '../contexts/ModeFilterContext';

// Mock EventSource
class MockEventSource {
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  static mockInstances: MockEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    MockEventSource.mockInstances.push(this);
    // Simulate connection open on next tick
    setTimeout(() => {
      if (this.onopen) this.onopen();
    }, 0);
  }

  emitMessage(data: any) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }

  emitError() {
    if (this.onerror) {
      this.onerror();
    }
  }
}

vi.stubGlobal('EventSource', MockEventSource);

describe('useSSEEvents', () => {
  let queryClient: QueryClient;
  let wrapper: any;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ModeFilterProvider>
          {children}
        </ModeFilterProvider>
      </QueryClientProvider>
    );
    vi.clearAllMocks();
    vi.useFakeTimers();
    MockEventSource.mockInstances = [];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('connects with channels parameter when provided', () => {
    const channels = ['dashboard', 'agi_control'];
    renderHook(() => useSSEEvents({ channels }), { wrapper });

    expect(MockEventSource.mockInstances[0].url).toContain(
      `${API_BASE}/api/v1/events/stream?channels=dashboard%2Cagi_control`
    );
  });

  it('connects without channels parameter when not provided', () => {
    renderHook(() => useSSEEvents(), { wrapper });

    expect(MockEventSource.mockInstances[0].url).toContain(
      `${API_BASE}/api/v1/events/stream`
    );
  });

  it('connects without channels parameter when not provided', () => {
    renderHook(() => useSSEEvents(), { wrapper });

    expect(MockEventSource.mockInstances[0].url).toContain(
      `${API_BASE}/api/v1/events/stream`
    );
    // Should not have a ?channels= query param
    expect(MockEventSource.mockInstances[0].url).not.toContain('channels=');
  });

  it('parses events and updates buffer', async () => {
    const { result } = renderHook(() => useSSEEvents(), { wrapper });

    // Get the instance created by the hook
    const esInstance = MockEventSource.mockInstances[0];

    const eventData = {
      event_type: 'trade_executed',
      timestamp: new Date().toISOString(),
      data: { tradeId: '123' }
    };

    await act(async () => {
      esInstance.emitMessage(eventData);
    });

    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0]).toEqual(eventData);
    expect(result.current.lastEvent).toEqual(eventData);
  });

  it('invalidates queries on trade_executed event', async () => {
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    renderHook(() => useSSEEvents(), { wrapper });

    const esInstance = MockEventSource.mockInstances[0];

    const eventData = {
      event_type: 'trade_executed',
      timestamp: new Date().toISOString(),
      data: {}
    };

    await act(async () => {
      esInstance.emitMessage(eventData);
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['trades'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['stats'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['dashboard'] });
  });

  it('does not connect when enabled=false', () => {
    renderHook(() => useSSEEvents({ enabled: false }), { wrapper });

    expect(MockEventSource.mockInstances).toHaveLength(0);
  });

  it('reconnects on error after 5s delay', async () => {
    const { result } = renderHook(() => useSSEEvents(), { wrapper });

    const esInstance = MockEventSource.mockInstances[0];

    await act(async () => {
      esInstance.emitError();
    });

    expect(result.current.status).toBe('disconnected');

    // Fast forward 5 seconds
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    // Should have created a new EventSource
    expect(MockEventSource.mockInstances).toHaveLength(2);
  });

  it('cleans up EventSource on unmount', () => {
    const { unmount } = renderHook(() => useSSEEvents(), { wrapper });
    const esInstance = MockEventSource.mockInstances[0];

    unmount();

    expect(esInstance.close).toHaveBeenCalled();
  });

  it('maintains a rolling buffer of 50 events', async () => {
    const { result } = renderHook(() => useSSEEvents(), { wrapper });
    const esInstance = MockEventSource.mockInstances[0];

    await act(async () => {
      for (let i = 0; i < 60; i++) {
        esInstance.emitMessage({
          event_type: 'trade_executed',
          timestamp: new Date().toISOString(),
          data: { i }
        });
      }
    });

    expect(result.current.events).toHaveLength(50);
    // Most recent event should be the last one sent
    expect(result.current.events[0].data).toEqual({ i: 59 });
  });
});
