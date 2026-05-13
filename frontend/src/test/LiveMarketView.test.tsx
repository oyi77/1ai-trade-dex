import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import LiveMarketView from '../components/LiveMarketView';

class MockWS {
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  readyState = 1;
  send = vi.fn();
  close = vi.fn();
  constructor(url: string) { void url; setTimeout(() => this.onopen?.({} as Event), 0); }
}

describe('LiveMarketView', () => {
  beforeEach(() => {
    (window as unknown as { WebSocket: typeof MockWS }).WebSocket = MockWS;
  });

  it('renders empty state when no data', () => {
    render(<LiveMarketView url="ws://test" />);
    expect(screen.getByText(/Waiting for market data/i)).toBeInTheDocument();
  });
});
