import { useState, useCallback, useRef, forwardRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTradeEvents, TradeEvent } from '../hooks/useTradeEvents'
import { simulateTrade, fetchSignalConfig } from '../api'

// Fallback defaults (overridden by backend settings at runtime)
const FALLBACK_NOTIFICATION_DURATION = Number(import.meta.env.VITE_SIGNAL_NOTIFICATION_DURATION) || 10000

type Tier = 'info' | 'small' | 'medium' | 'large' | 'whale'
type Side = 'win' | 'loss' | 'neutral'

interface SignalContext {
  market_ticker: string
  market_title: string
  platform: string
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number
  suggested_size: number
  reasoning: string
  timestamp: string
  category: string
  btc_price: number
  btc_change_24h: number
  window_end?: string
  actionable: boolean
  event_slug?: string
}

interface Notification {
  id: string
  type: 'trade_opened' | 'trade_settled' | 'signal_found'
  title: string
  body: string
  tier: Tier
  side: Side
  pnl?: number
  size?: number
  expiresAt: number
  ticker?: string
  direction?: string
  units?: number
  multiplier?: number
  ageLabel?: string
  createdAt: number
  signalContext?: SignalContext
}

const MAX_VISIBLE = 6

const TIER_DURATIONS: Record<Tier, number> = {
  whale: 8000,
  large: 6000,
  medium: 4000,
  small: 3000,
  info: FALLBACK_NOTIFICATION_DURATION,
}

function getTier(amount: number): Tier {
  const abs = Math.abs(amount)
  if (abs > 100) return 'whale'
  if (abs > 50) return 'large'
  if (abs > 20) return 'medium'
  if (abs > 5) return 'small'
  return 'info'
}

function getCardStyle(tier: Tier, side: Side): { border: string; titleColor: string; glow?: string } {
  if (side === 'win') {
    if (tier === 'whale') return { border: '#fbbf24', titleColor: '#fbbf24', glow: '0 0 12px rgba(251,191,36,0.4)' }
    if (tier === 'large') return { border: '#22c55e', titleColor: '#22c55e' }
    if (tier === 'medium') return { border: '#16a34a', titleColor: '#16a34a' }
    return { border: '#15803d', titleColor: '#15803d' }
  }
  if (side === 'loss') {
    if (tier === 'whale') return { border: '#7f1d1d', titleColor: '#ef4444', glow: '0 0 12px rgba(239,68,68,0.4)' }
    if (tier === 'large') return { border: '#ef4444', titleColor: '#ef4444' }
    if (tier === 'medium') return { border: '#dc2626', titleColor: '#dc2626' }
    return { border: '#991b1b', titleColor: '#dc2626' }
  }
  // neutral / signal
  if (tier === 'info') return { border: '#f59e0b', titleColor: '#f59e0b' }
  return { border: '#38bdf8', titleColor: '#38bdf8' }
}

function formatAge(ms: number): string {
  if (ms < 1000) return `${ms}ms ago`
  if (ms < 60000) return `${Math.floor(ms / 1000)}s ago`
  return `${Math.floor(ms / 60000)}m ago`
}

function calculateTimeRemaining(windowEnd: string): string {
  const endTime = new Date(windowEnd).getTime()
  const now = Date.now()
  const remaining = endTime - now

  if (remaining <= 0) return 'Expired'

  const hours = Math.floor(remaining / 3600000)
  const minutes = Math.floor((remaining % 3600000) / 60000)

  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  return `${minutes}m`
}

async function handleApproveSignal(signalContext: SignalContext) {
  try {
    // Simulate trade for this signal
    const result = await simulateTrade(signalContext.market_ticker)
    if (import.meta.env.DEV) console.log(`Trade approved for ${signalContext.market_ticker}:`, result)
  } catch (error) {
    console.error('Failed to approve signal:', error)
  }
}

function handleSkipSignal(_signalContext: SignalContext) {
  // Skipped signal tracked server-side
}

function mapEventToNotification(
  event: TradeEvent,
  approvalMode: 'manual' | 'auto_approve' | 'auto_deny',
  notificationDuration: number
): Notification | null {
  const now = Date.now()
  const id = `${now}-${Math.random().toString(36).slice(2, 7)}`

  if (event.type === 'connected') return null

  if (event.type === 'signal_found') {
    const ticker = String(event.data.market_ticker ?? event.data.ticker ?? event.data.symbol ?? event.data.condition_id ?? 'Unknown Market')
    const direction = String(event.data.direction ?? event.data.side ?? event.data.action ?? 'WAIT')
    const modelProb = Number(event.data.model_probability ?? event.data.probability ?? 0.5)
    const confidence = event.data.confidence != null ? `${(Number(event.data.confidence) * 100).toFixed(0)}%` : 'N/A'
    const title = String(event.data.market_title ?? event.data.question ?? ticker)
    const platform = String(event.data.platform ?? event.data.source ?? 'Polymarket')
    const signalContext: SignalContext = {
      market_ticker: ticker,
      market_title: title,
      platform,
      direction,
      model_probability: modelProb,
      market_probability: Number(event.data.market_probability ?? event.data.yes_price ?? 0.5),
      edge: Number(event.data.edge ?? 0),
      confidence: Number(event.data.confidence ?? 0.5),
      suggested_size: Number(event.data.suggested_size ?? event.data.position_size ?? 0),
      reasoning: String(event.data.reasoning ?? event.data.analysis ?? 'Signal detected'),
      timestamp: String(event.data.timestamp ?? new Date().toISOString()),
      category: String(event.data.category ?? 'trading'),
      btc_price: Number(event.data.btc_price ?? 0),
      btc_change_24h: Number(event.data.btc_change_24h ?? 0),
      window_end: event.data.window_end ? String(event.data.window_end) : undefined,
      actionable: Boolean(event.data.actionable ?? true),
      event_slug: event.data.event_slug ? String(event.data.event_slug) : undefined,
    }

    // In manual mode, use longer duration for user to decide
    const duration = approvalMode === 'manual' ? notificationDuration : TIER_DURATIONS.info

    return {
      id,
      type: 'signal_found',
      title: `${direction.toUpperCase()} • ${(modelProb * 100).toFixed(0)}% model • ${confidence} conf`,
      body: `${platform}: ${title.slice(0, 40)}${title.length > 40 ? '...' : ''}`,
      tier: 'info',
      side: 'neutral',
      ticker,
      signalContext,
      expiresAt: now + duration,
      createdAt: now,
    }
  }

  if (event.type === 'trade_opened') {
    const size = Number(event.data.size ?? event.data.notional ?? 0)
    const ticker = String(event.data.market_ticker ?? event.data.ticker ?? event.data.symbol ?? '—')
    const direction = String(event.data.direction ?? event.data.side ?? '')
    const units = Number(event.data.units ?? event.data.qty ?? 0)
    const multiplier = Number(event.data.multiplier ?? event.data.leverage ?? 1)
    const tier = getTier(size)
    return {
      id,
      type: 'trade_opened',
      title: 'OPENED',
      body: ticker,
      tier,
      side: 'neutral',
      size,
      ticker,
      direction,
      units,
      multiplier,
      expiresAt: now + TIER_DURATIONS[tier],
      createdAt: now,
    }
  }

  if (event.type === 'trade_settled') {
    const pnl = Number(event.data.pnl ?? 0)
    const result = String(event.data.result ?? (pnl >= 0 ? 'win' : 'loss'))
    const side: Side = result === 'win' ? 'win' : 'loss'
    const ticker = String(event.data.market_ticker ?? event.data.ticker ?? event.data.symbol ?? '—')
    const direction = String(event.data.direction ?? event.data.side ?? '')
    const units = Number(event.data.units ?? event.data.qty ?? 0)
    const multiplier = Number(event.data.multiplier ?? event.data.leverage ?? 1)
    const tier = getTier(Math.abs(pnl))
    return {
      id,
      type: 'trade_settled',
      title: 'SETTLED',
      body: ticker,
      tier,
      side,
      pnl,
      ticker,
      direction,
      units,
      multiplier,
      expiresAt: now + TIER_DURATIONS[tier],
      createdAt: now,
    }
  }

  return null
}

function TierBadge({ tier, side }: { tier: Tier; side: Side }) {
  const { titleColor } = getCardStyle(tier, side)
  const label = tier.toUpperCase()
  return (
    <span
      className="font-mono text-[9px] font-700 uppercase tracking-wider px-1 py-0.5 border"
      style={{
        color: titleColor,
        borderColor: titleColor,
        background: `${titleColor}18`,
        fontWeight: 700,
      }}
    >
      {label}
    </span>
  )
}

const NotificationCard = forwardRef(function NotificationCard({
  notification,
  onDismiss,
  approvalMode,
}: {
  notification: Notification
  onDismiss: (id: string) => void
  approvalMode: 'manual' | 'auto_approve' | 'auto_deny'
}, ref: React.Ref<HTMLDivElement>) {
  const { border, titleColor, glow } = getCardStyle(notification.tier, notification.side)
  const age = formatAge(Date.now() - notification.createdAt)

  const pnlDisplay =
    notification.pnl !== undefined
      ? `${notification.pnl >= 0 ? '+' : ''}$${Math.abs(notification.pnl).toFixed(2)}`
      : notification.size !== undefined
      ? `$${notification.size.toFixed(2)}`
      : ''

  const sideLabel =
    notification.side === 'win' ? 'WIN' : notification.side === 'loss' ? 'LOSS' : ''

  // Show full context for signals
  if (notification.type === 'signal_found' && notification.signalContext) {
    const ctx = notification.signalContext
    const timeRemaining = ctx.window_end ? calculateTimeRemaining(ctx.window_end) : null

    return (
      <motion.div
        ref={ref}
        layout
        initial={{ x: 60, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 60, opacity: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className="cursor-pointer select-none"
        style={{
          background: 'rgb(10,10,10)',
          border: `1px solid ${border}`,
          boxShadow: glow ?? 'none',
          width: 320,
          fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
        }}
      >
        <div className="p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-2">
            <TierBadge tier={notification.tier} side={notification.side} />
            <span className="text-[9px] text-neutral-500">{age}</span>
          </div>

          {/* Market Info */}
          <div className="mb-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] text-neutral-500 uppercase">MARKET</span>
              <span className="text-[11px] font-semibold text-neutral-100 truncate">{ctx.market_title}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-neutral-500 uppercase">PLATFORM</span>
              <span className="text-[9px] text-neutral-300">{ctx.platform}</span>
            </div>
          </div>

          {/* Direction & Probabilities */}
          <div className="mb-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-bold uppercase" style={{ color: titleColor }}>
                {ctx.direction}
              </span>
              <span className="text-[10px] text-neutral-500">Model</span>
              <span className="text-[10px] font-mono font-semibold text-green-400">{((ctx.model_probability ?? 0) * 100).toFixed(1)}%</span>
              <span className="text-[10px] text-neutral-500">Market</span>
              <span className="text-[10px] font-mono font-semibold text-neutral-400">{((ctx.market_probability ?? 0) * 100).toFixed(1)}%</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-neutral-500">Edge</span>
              <span className="text-[10px] font-bold text-amber-400">{((ctx.edge ?? 0) * 100).toFixed(1)}%</span>
              <span className="text-[10px] text-neutral-500">Kelly</span>
              <span className="text-[10px] font-mono font-semibold text-blue-400">${(ctx.suggested_size ?? 0).toFixed(0)}</span>
            </div>
          </div>

          {/* Additional Context */}
          <div className="mb-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[9px] text-neutral-500 uppercase">CONFIDENCE</span>
              <span className="text-[9px] font-mono font-semibold text-cyan-400">{((ctx.confidence ?? 0) * 100).toFixed(0)}%</span>
            </div>
            {timeRemaining && (
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-neutral-500 uppercase">EXPIRES</span>
                <span className="text-[9px] font-mono text-neutral-300">{timeRemaining}</span>
              </div>
            )}
          </div>

          {/* Action Buttons - only show in manual approval mode */}
          {ctx.actionable && approvalMode === 'manual' && (
            <div className="flex gap-1 mt-2">
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleApproveSignal(ctx)
                  onDismiss(notification.id)
                }}
                className="flex-1 px-2 py-1 text-[9px] font-bold uppercase bg-green-500/10 text-green-400 border border-green-500/20 hover:bg-green-500/20 transition-colors"
              >
                APPROVE
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleSkipSignal(ctx)
                  onDismiss(notification.id)
                }}
                className="flex-1 px-2 py-1 text-[9px] font-bold uppercase bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors"
              >
                SKIP
              </button>
            </div>
          )}
        </div>
      </motion.div>
    )
  }

  // Regular notification for trades
  return (
    <motion.div
      ref={ref}
      layout
      initial={{ x: 60, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 60, opacity: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      onClick={() => onDismiss(notification.id)}
      className="cursor-pointer select-none"
      style={{
        background: 'rgb(10,10,10)',
        border: `1px solid ${border}`,
        boxShadow: glow ?? 'none',
        width: 260,
        padding: '6px 8px',
        fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
      }}
    >
      {/* Row 1: badge + direction + ticker + pnl */}
      <div className="flex items-center gap-1.5 mb-0.5">
        <TierBadge tier={notification.tier} side={notification.side} />
        {notification.direction && (
          <span className="text-[10px] text-neutral-300 uppercase font-mono font-semibold">
            {notification.direction}
          </span>
        )}
        <span className="text-[11px] font-mono font-semibold flex-1 truncate" style={{ color: titleColor }}>
          {notification.ticker}
        </span>
        {pnlDisplay && (
          <span className="text-[11px] font-mono font-semibold" style={{ color: titleColor }}>
            {pnlDisplay}
          </span>
        )}
      </div>

      {/* Row 2: subtitle + side label + age */}
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-neutral-500 font-mono flex-1">
          {notification.type === 'signal_found'
            ? 'signal detected'
            : notification.multiplier && notification.units
            ? `${notification.multiplier}× ${notification.units} units`
            : notification.title.toLowerCase()}
        </span>
        {sideLabel && (
          <span className="text-[9px] font-mono font-semibold" style={{ color: titleColor }}>
            {sideLabel}
          </span>
        )}
        <span className="text-[9px] text-neutral-600 font-mono">{age}</span>
      </div>
    </motion.div>
  )
})

export function useNotifications() {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const addNotification = useCallback(
    (notif: Notification) => {
      setNotifications((prev) => {
        const next = [notif, ...prev].slice(0, MAX_VISIBLE)
        return next
      })

      const timer = setTimeout(() => {
        dismiss(notif.id)
      }, notif.expiresAt - Date.now())

      timersRef.current.set(notif.id, timer)
    },
    [dismiss]
  )

  return { notifications, addNotification, dismiss }
}

export function TradeNotifications() {
  const { notifications, addNotification, dismiss } = useNotifications()

  // Fetch signal approval config from backend
  const [signalConfig, setSignalConfig] = useState<{
    approvalMode: 'manual' | 'auto_approve' | 'auto_deny'
    minConfidence: number
    notificationDuration: number
  }>({
    approvalMode: (import.meta.env.VITE_SIGNAL_APPROVAL_MODE as 'manual' | 'auto_approve' | 'auto_deny') || 'manual',
    minConfidence: 0.85,
    notificationDuration: Number(import.meta.env.VITE_SIGNAL_NOTIFICATION_DURATION) || 10000,
  })

  useEffect(() => {
    fetchSignalConfig().then((cfg) => {
      setSignalConfig({
        approvalMode: cfg.approval_mode,
        minConfidence: cfg.min_confidence,
        notificationDuration: cfg.notification_duration_ms || 30000, // Default to 30s for manual mode
      })
    }).catch(() => {
      // Fallback to env vars already set in initial state
    })
  }, [])

  const handleEvent = useCallback(
    (event: TradeEvent) => {
      // Filter signals below the minimum confidence threshold
      if (event.type === 'signal_found') {
        const confidence = Number(event.data.confidence ?? 0)
        if (confidence < signalConfig.minConfidence) return
      }

      const notif = mapEventToNotification(event, signalConfig.approvalMode, signalConfig.notificationDuration)
      if (!notif) return

      // Auto-approval and auto-deny are handled server-side by the backend
      // scheduler. The frontend only displays notifications.
      if (notif.type === 'signal_found' && notif.signalContext) {
        if (signalConfig.approvalMode === 'auto_approve' || signalConfig.approvalMode === 'auto_deny') {
          // Do not execute trades from the frontend; just skip the notification
          return
        }
      }

      addNotification(notif)
    },
    [addNotification, signalConfig.approvalMode, signalConfig.minConfidence, signalConfig.notificationDuration]
  )

  useTradeEvents(handleEvent)

  return (
    <div
      className="fixed z-50 flex flex-col-reverse gap-2"
      style={{ bottom: '1rem', right: '1rem' }}
    >
      <AnimatePresence mode="popLayout">
        {notifications.map((n) => (
          <NotificationCard key={n.id} notification={n} onDismiss={dismiss} approvalMode={signalConfig.approvalMode} />
        ))}
      </AnimatePresence>
    </div>
  )
}
