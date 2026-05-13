import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import TradingTerminal from '../pages/TradingTerminal';

class MockWS {
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  readyState = 1;
  send = vi.fn();
  close = vi.fn();
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  constructor(_url: string) { setTimeout(() => this.onopen?.({} as Event), 0); }
}

describe('TradingTerminal', () => {
  beforeEach(() => {
    (window as unknown as { WebSocket: typeof MockWS }).WebSocket = MockWS;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ opportunities: [] }),
    }));
  });

  it('renders Trading Terminal heading', () => {
    render(<TradingTerminal />);
    expect(screen.getByText('Trading Terminal')).toBeInTheDocument();
  });
});
