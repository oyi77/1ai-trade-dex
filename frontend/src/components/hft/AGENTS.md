<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend/src/components/hft

## Purpose

High-Frequency Trading (HFT) UI components for real-time monitoring and control of HFT strategies. Provides dashboard interface for strategy management, signal visualization, metrics tracking, and real-time performance monitoring.

## Key Files

| File | Description |
|------|-------------|
| `index.tsx` | Export module - exports HFT components and default dashboard container |
| `HFTDashboard.tsx` | Main HFT dashboard container - strategy toggle controls, real-time metrics display, and signal management interface |
| `HFTSignals.tsx` | HFT signal display component - real-time signal feed with edge/confidence/size indicators, strategy filtering, and status tracking |
| `HFTMetrics.tsx` | HFT metrics monitoring - performance cards, strategy status grid, latency indicators, and real-time health metrics |

## For AI Agents

### Working In This Directory
- All components use React Query for real-time data fetching with configurable polling intervals
- Strategy toggles use optimistic updates with mutation invalidation
- Signal displays use Framer Motion animations for real-time updates
- Metrics cards show performance indicators with color-coded status
- WebSocket connections handle real-time data streams with exponential backoff

### Testing Requirements
- Mock API responses for HFT strategy and signal data
- Test mutation strategies for strategy enable/disable operations
- Verify WebSocket reconnection logic and error handling
- Test responsive layout across different screen sizes
- Validate real-time update performance with mock data streams

### Common Patterns
- Use `useQuery({ queryKey: ['hft-strategies'], queryFn: fetchHFTStrategies })` for data fetching
- Implement strategy toggles with `useMutation` and `onSuccess` invalidation
- Display real-time signals with `AnimatePresence` for enter/exit animations
- Show metrics cards with conditional styling based on performance thresholds
- Export components via `index.tsx` for consistent import patterns

## Dependencies

### Internal
- `../../api` - REST API client for HFT endpoints
- `../../polling` - Polling interval configuration (POLL.NORMAL, etc.)
- `../../types` - TypeScript interfaces for HFT data structures

### External
- `@tanstack/react-query` - Server state management and caching
- `framer-motion` - Animation and transition effects
- `lucide-react` - Icon components for visual indicators
- `react` - Core React functionality with hooks