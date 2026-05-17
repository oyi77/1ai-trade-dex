import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  Zap, Brain, Activity, Radio, ChevronRight,
  Signal, Shield, DollarSign, AlertTriangle,
  TrendingUp, TrendingDown, Mic, Play, Pause,
  RefreshCw, Wifi, WifiOff, Grid3X3
} from 'lucide-react'

import { getWsUrl } from '../api'

interface DecisionCard {
  id: string
  signal: string
  timestamp: string | number
  stage: 'detected' | 'analyzing' | 'debate' | 'judge' | 'risk' | 'executed' | 'blocked'
  bullReason?: string
  bearReason?: string
  verdict?: 'bull' | 'bear' | null
  riskScore?: number
  decision?: 'executed' | 'blocked'
  confidence?: number
  source?: string
  strategy?: string
}

interface StrategyPulse {
  name: string
  status: 'thinking' | 'fired' | 'idle'
  lastPulse: number
}

const PIPELINE_STAGES = ['detected', 'analyzing', 'debate', 'judge', 'risk', 'executed', 'blocked'] as const

export function LiveStreamPanel() {
  const [activeTab, setActiveTab] = useState<'all' | 'pipeline' | 'arena' | 'pulse' | 'thoughts'>('all')
  const [isLive, setIsLive] = useState(true)
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [cards, setCards] = useState<DecisionCard[]>([])
  const [bullText, setBullText] = useState<string | undefined>(undefined)
  const [bearText, setBearText] = useState<string | undefined>(undefined)
  const [verdict, setVerdict] = useState<'bull' | 'bear' | null>(null)
  const [isDebating, setIsDebating] = useState(false)
  const [strategies, setStrategies] = useState<StrategyPulse[]>([])
  const [thoughts, setThoughts] = useState<{ id: string; text: string; timestamp: number }[]>([])
  const [botState, setBotState] = useState<{
    bankroll: number
    totalPnl: number
    totalTrades: number
    isRunning: boolean
  } | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef(0)
  const maxReconnect = 5

  const connectWs = useCallback(() => {
    if (reconnectRef.current >= maxReconnect) {
      setWsStatus('disconnected')
      return
    }

    const ws = new WebSocket(getWsUrl('/ws/livestream'))

    wsRef.current = ws
    setWsStatus('connecting')

    ws.onopen = () => {
      reconnectRef.current = 0
      setWsStatus('connected')
    }

    ws.onmessage = (evt: MessageEvent) => {
      try {
        const msg = JSON.parse(evt.data)

        switch (msg.type) {
          case 'subscribed':
            console.log('[LiveStream] Subscribed to livestream')
            break

          case 'livestream_snapshot':
            if (msg.pipeline_cards) {
              setCards(msg.pipeline_cards.map((c: any) => ({
                ...c,
                timestamp: c.timestamp ? new Date(c.timestamp) : new Date()
              })))
            }
            if (msg.pulse_strategies) {
              setStrategies(msg.pulse_strategies.map((s: any) => ({
                name: s.name,
                status: s.status || 'idle',
                lastPulse: s.last_pulse || Date.now()
              })))
            }
            break

          case 'pipeline_update':
            if (msg.action === 'card_added') {
              setCards(prev => {
                const updated = [...prev, { ...msg.card, timestamp: new Date(msg.card.timestamp) }]
                return updated.slice(-50)
              })
            } else if (msg.action === 'stage_transition') {
              setCards(prev => prev.map(c => {
                if (c.id === msg.card_id) {
                  return { ...c, stage: msg.stage, ...msg }
                }
                return c
              }))
            }
            break

          case 'arena_update':
            setBullText(msg.bull_text || '')
            setBearText(msg.bear_text || '')
            setVerdict(msg.verdict || null)
            setIsDebating(msg.is_debating !== false)
            break

          case 'pulse_update':
            setStrategies(prev => {
              const updated = prev.filter(s => s.name !== msg.strategy)
              return [...updated, {
                name: msg.strategy,
                status: msg.status || 'idle',
                lastPulse: msg.timestamp ? new Date(msg.timestamp).getTime() : Date.now()
              }]
            })
            break

          case 'trade_event':
            if (msg.action === 'trade_executed' || msg.action === 'trade_blocked') {
              const trade = msg.trade
              if (trade) {
                const newCard: DecisionCard = {
                  id: `trade_${trade.id}`,
                  signal: trade.market_ticker || 'Unknown',
                  stage: msg.action === 'trade_executed' ? 'executed' : 'blocked',
                  timestamp: trade.timestamp ? (typeof trade.timestamp === 'string' ? trade.timestamp : Date.now()) : Date.now(),
                  decision: msg.action === 'trade_executed' ? 'executed' : 'blocked',
                  confidence: trade.confidence,
                  source: trade.signal_source,
                  strategy: trade.strategy
                }
                setCards(prev => {
                  const updated = [...prev, newCard]
                  return updated.slice(-50)
                })
              }
            }
            break

          case 'thought_log':
            if (msg.text) {
              setThoughts(prev => {
                const updated = [...prev, { id: msg.id || Date.now().toString(), text: msg.text, timestamp: msg.timestamp ? new Date(msg.timestamp).getTime() : Date.now() }]
                return updated.slice(-100)
              })
            }
            break

          case 'bot_state':
            setBotState({
              bankroll: msg.bankroll || 0,
              totalPnl: msg.total_pnl || 0,
              totalTrades: msg.total_trades || 0,
              isRunning: msg.is_running || false
            })
            break
        }
      } catch (e) {
        console.error('[LiveStream] Parse error:', e)
      }
    }

    ws.onerror = () => {}

    ws.onclose = () => {
      if (reconnectRef.current < maxReconnect) {
        reconnectRef.current++
        setWsStatus('connecting')
        setTimeout(connectWs, Math.min(5000, 1000 * Math.pow(2, reconnectRef.current - 1)))
      } else {
        setWsStatus('disconnected')
      }
    }
  }, [])

  useEffect(() => {
    connectWs()
    return () => {
      reconnectRef.current = maxReconnect
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
    }
  }, [connectWs])

  return (
    <div className="h-full bg-black overflow-hidden flex flex-col">
      <LiveStreamHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isLive={isLive}
        setIsLive={setIsLive}
        wsStatus={wsStatus}
        botState={botState}
      />

      <div className="flex-1 overflow-hidden">
        {activeTab === 'all' ? (
          <div className="h-full grid grid-cols-1 lg:grid-cols-2 grid-rows-2 gap-2 p-2">
            <div className="bg-neutral-900 rounded-lg overflow-hidden">
              <PipelineView isLive={isLive} cards={cards} />
            </div>
            <div className="bg-neutral-900 rounded-lg overflow-hidden">
              <ArenaView
                isLive={isLive}
                bullText={bullText}
                bearText={bearText}
                verdict={verdict}
                isDebating={isDebating}
              />
            </div>
            <div className="bg-neutral-900 rounded-lg overflow-hidden">
              <ThoughtStreamView isLive={isLive} thoughts={thoughts} />
            </div>
            <div className="bg-neutral-900 rounded-lg overflow-hidden">
              <PulseView isLive={isLive} strategies={strategies} />
            </div>
          </div>
        ) : activeTab === 'pipeline' ? (
          <PipelineView isLive={isLive} cards={cards} fullPage />
        ) : activeTab === 'arena' ? (
          <ArenaView
            isLive={isLive}
            bullText={bullText}
            bearText={bearText}
            verdict={verdict}
            isDebating={isDebating}
            fullPage
          />
        ) : activeTab === 'thoughts' ? (
          <ThoughtStreamView isLive={isLive} thoughts={thoughts} fullPage />
        ) : (
          <PulseView isLive={isLive} strategies={strategies} fullPage />
        )}
      </div>
    </div>
  )
}

function LiveStreamHeader({ activeTab, setActiveTab, isLive, setIsLive, wsStatus, botState }: {
  activeTab: 'all' | 'pipeline' | 'arena' | 'pulse' | 'thoughts'
  setActiveTab: (t: 'all' | 'pipeline' | 'arena' | 'pulse' | 'thoughts') => void
  isLive: boolean
  setIsLive: (v: boolean) => void
  wsStatus?: 'connecting' | 'connected' | 'disconnected'
  botState?: {
    bankroll: number
    totalPnl: number
    totalTrades: number
    isRunning: boolean
  } | null
}) {
  const tabs = [
    { id: 'all', label: 'All Views', icon: Grid3X3 },
    { id: 'pipeline', label: 'Pipeline', icon: Kanban },
    { id: 'arena', label: 'Arena', icon: Mic },
    { id: 'thoughts', label: 'Thoughts', icon: Brain },
    { id: 'pulse', label: 'Pulse', icon: Activity },
  ] as const

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-neutral-800 bg-neutral-900/80">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Radio className={`w-4 h-4 ${isLive ? 'text-green-500 animate-pulse' : 'text-neutral-500'}`} />
          <span className="text-sm font-bold text-neutral-100 uppercase tracking-wider">Live Stream</span>
          {wsStatus === 'connected' ? (
            <Wifi className="w-3 h-3 text-green-400" />
          ) : wsStatus === 'connecting' ? (
            <RefreshCw className="w-3 h-3 text-yellow-400 animate-spin" />
          ) : (
            <WifiOff className="w-3 h-3 text-red-400" />
          )}
        </div>

        {botState && (
          <div className="hidden md:flex items-center gap-3 ml-4 text-[10px] text-neutral-400">
            <span>Bankroll: <span className="text-green-400">${botState.bankroll.toFixed(2)}</span></span>
            <span>P&L: <span className={botState.totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}>
              {botState.totalPnl >= 0 ? '+' : ''}{botState.totalPnl.toFixed(2)}
            </span></span>
            <span>Trades: <span className="text-neutral-200">{botState.totalTrades}</span></span>
          </div>
        )}
      </div>

      <div className="flex gap-1 ml-4">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1.5 text-xs uppercase tracking-wider rounded transition-colors ${
              activeTab === tab.id
                ? 'bg-green-500/20 text-green-400 border border-green-500/40'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <button
        onClick={() => setIsLive(!isLive)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded border transition-colors ${
          isLive
            ? 'bg-red-500/20 border-red-500/40 text-red-400'
            : 'bg-neutral-800 border-neutral-700 text-neutral-400'
        }`}
      >
        {isLive ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
        <span className="text-xs uppercase tracking-wider">{isLive ? 'Pause' : 'Play'}</span>
      </button>
    </div>
  )
}

function Kanban({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <rect x="1" y="2" width="4" height="12" rx="1" />
      <rect x="6" y="2" width="4" height="12" rx="1" />
      <rect x="11" y="2" width="4" height="12" rx="1" />
    </svg>
  )
}

function PipelineView({ cards, fullPage = false }: {
  isLive: boolean
  cards?: DecisionCard[]
  fullPage?: boolean
}) {
  const displayCards = cards || []

  const stageLabels: Record<string, { label: string; icon: any; color: string }> = {
    detected: { label: 'Signal Detected', icon: Signal, color: 'text-blue-400' },
    analyzing: { label: 'AI Analyzing', icon: Brain, color: 'text-purple-400' },
    debate: { label: 'Bull vs Bear', icon: Zap, color: 'text-yellow-400' },
    judge: { label: 'Judge Decision', icon: TrendingUp, color: 'text-orange-400' },
    risk: { label: 'Risk Check', icon: Shield, color: 'text-cyan-400' },
    executed: { label: 'Trade Executed', icon: DollarSign, color: 'text-green-400' },
    blocked: { label: 'Blocked', icon: AlertTriangle, color: 'text-red-400' },
  }

  const getCardsForStage = (stage: string) => displayCards.filter(c => c.stage === stage)

  return (
    <div className={`h-full flex flex-col ${fullPage ? 'p-4' : 'p-2'}`}>
      <div className="flex items-center gap-2 mb-3 px-2">
        <Kanban className="w-4 h-4 text-green-500" />
        <span className="text-xs font-bold text-neutral-100 uppercase tracking-wider">Decision Pipeline</span>
        <span className="text-[10px] text-neutral-500 ml-auto">
          {displayCards.length} signals
        </span>
      </div>

      <div className="flex-1 flex gap-2 overflow-x-auto pb-2">
        {PIPELINE_STAGES.map((stage, i) => {
          const stageCards = getCardsForStage(stage)
          const info = stageLabels[stage]
          const Icon = info.icon

          return (
            <div key={stage} className="flex-shrink-0 w-28 flex flex-col">
              <div className={`flex items-center gap-1.5 mb-2 px-1 ${info.color}`}>
                <Icon className="w-3 h-3" />
                <span className="text-[10px] font-bold uppercase tracking-wider truncate">{info.label}</span>
              </div>

              <div className="flex-1 space-y-1.5 overflow-y-auto min-h-0">
                {stageCards.map(card => (
                  <motion.div
                    key={card.id}
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className="bg-neutral-800 border border-neutral-700 rounded p-2 cursor-pointer hover:border-green-500/40 transition-colors"
                  >
                    <div className="text-[9px] text-neutral-200 font-medium truncate">{card.signal}</div>
                    <div className="text-[8px] text-neutral-500 mt-1">
                      {typeof card.timestamp === 'number' ? new Date(card.timestamp).toLocaleTimeString() : card.timestamp.toString()}
                    </div>
                    {card.verdict && (
                      <div className={`text-[8px] mt-1 font-bold ${card.verdict === 'bull' ? 'text-green-400' : 'text-red-400'}`}>
                        {card.verdict.toUpperCase()}
                      </div>
                    )}
                    {card.confidence !== undefined && (
                      <div className="text-[8px] text-neutral-400 mt-1">
                        Conf: {(card.confidence * 100).toFixed(0)}%
                      </div>
                    )}
                  </motion.div>
                ))}
              </div>

              {i < PIPELINE_STAGES.length - 1 && (
                <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-full">
                  <ChevronRight className="w-3 h-3 text-neutral-600" />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ArenaView({ bullText, bearText, verdict, isDebating, fullPage = false }: {
  isLive: boolean
  bullText?: string
  bearText?: string
  verdict?: 'bull' | 'bear' | null
  isDebating?: boolean
  fullPage?: boolean;
}) {
  const displayBullText = bullText || ''
  const displayBearText = bearText || ''
  const displayVerdict = verdict || null
  const displayIsDebating = isDebating !== undefined ? isDebating : false
  const hasData = displayBullText || displayBearText

  return (
    <div className={`h-full flex flex-col ${fullPage ? 'p-4' : 'p-2'}`}>
      <div className="flex items-center gap-2 mb-3 px-2">
        <Mic className="w-4 h-4 text-yellow-500" />
        <span className="text-xs font-bold text-neutral-100 uppercase tracking-wider">AI Arena - Live Debate</span>
      </div>

      {!hasData ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Mic className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
            <p className="text-xs text-neutral-600">No active debate</p>
            <p className="text-[10px] text-neutral-700 mt-1">Trading signals will appear here</p>
          </div>
        </div>
      ) : (
        <>
          <div className="flex-1 grid grid-cols-2 gap-2">
            <div className="bg-green-900/20 border border-green-500/30 rounded-lg p-2 flex flex-col">
              <div className="flex items-center gap-1.5 mb-2">
                <TrendingUp className="w-3 h-3 text-green-400" />
                <span className="text-[10px] font-bold text-green-400 uppercase">Bull Case</span>
              </div>
              <div className="flex-1 overflow-y-auto">
                <p className="text-[10px] text-green-300/80 font-mono leading-relaxed whitespace-pre-line">
                  {displayBullText}
                  {displayIsDebating && <span className="animate-pulse">▊</span>}
                </p>
              </div>
            </div>

            <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-2 flex flex-col">
              <div className="flex items-center gap-1.5 mb-2">
                <TrendingDown className="w-3 h-3 text-red-400" />
                <span className="text-[10px] font-bold text-red-400 uppercase">Bear Case</span>
              </div>
              <div className="flex-1 overflow-y-auto">
                <p className="text-[10px] text-red-300/80 font-mono leading-relaxed whitespace-pre-line">
                  {displayBearText}
                  {displayIsDebating && <span className="animate-pulse">▊</span>}
                </p>
              </div>
            </div>
          </div>

          {displayVerdict && (
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className={`mt-2 p-2 rounded-lg border text-center ${
                displayVerdict === 'bull'
                  ? 'bg-green-500/20 border-green-500/40'
                  : 'bg-red-500/20 border-red-500/40'
              }`}
            >
              <div className={`text-xs font-bold uppercase tracking-wider ${
                displayVerdict === 'bull' ? 'text-green-400' : 'text-red-400'
              }`}>
                Judge Verdict: {displayVerdict === 'bull' ? '🟢 BULL' : '🔴 BEAR'}
              </div>
            </motion.div>
          )}
        </>
      )}
    </div>
  )
}

function PulseView({ strategies, fullPage = false }: {
  isLive: boolean
  strategies?: StrategyPulse[]
  fullPage?: boolean;
}) {
  const displayStrategies = strategies || []

  return (
    <div className={`h-full flex flex-col ${fullPage ? 'p-4' : 'p-2'}`}>
      <div className="flex items-center gap-2 mb-3 px-2">
        <Activity className="w-4 h-4 text-purple-500" />
        <span className="text-xs font-bold text-neutral-100 uppercase tracking-wider">Neural Pulse</span>
        <span className="text-[10px] text-neutral-500">
          {displayStrategies.length > 0 ? `${displayStrategies.length} strategies` : 'No strategy data'}
        </span>
      </div>

      {displayStrategies.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Activity className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
            <p className="text-xs text-neutral-600">No strategy pulses yet</p>
            <p className="text-[10px] text-neutral-700 mt-1">Strategy data streams from live trading</p>
          </div>
        </div>
      ) : (
        <div className="flex-1 grid grid-cols-3 gap-2 content-start">
          {displayStrategies.slice(0, 12).map(s => (
            <div key={s.name} className="bg-neutral-800/50 rounded px-2 py-1 flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${
                s.status === 'thinking' ? 'bg-purple-500 animate-pulse' :
                s.status === 'fired' ? 'bg-green-500' : 'bg-neutral-600'
              }`} />
              <span className="text-[9px] text-neutral-400 truncate">{s.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ThoughtStreamView({ isLive, thoughts, fullPage = false }: {
  isLive: boolean
  thoughts?: { id: string; text: string; timestamp: number }[]
  fullPage?: boolean
}) {
  const displayThoughts = useMemo(() => thoughts || [], [thoughts])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [displayThoughts])

  return (
    <div className={`h-full flex flex-col ${fullPage ? 'p-4' : 'p-2'}`}>
      <div className="flex items-center gap-2 mb-3 px-2">
        <Brain className="w-4 h-4 text-cyan-500" />
        <span className="text-xs font-bold text-neutral-100 uppercase tracking-wider">Thought Stream</span>
        <span className="text-[10px] text-neutral-500 ml-auto">
          {displayThoughts.length > 0 ? `${displayThoughts.length} thoughts` : ''}
        </span>
      </div>
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-neutral-950 border border-neutral-800 rounded p-3 font-mono text-[10px] text-green-500 leading-relaxed"
      >
        {displayThoughts.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Brain className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
              <p className="text-xs text-neutral-600">No thought stream data</p>
              <p className="text-[10px] text-neutral-700 mt-1">AI reasoning will appear here</p>
            </div>
          </div>
        ) : (
          displayThoughts.map(t => (
            <div key={t.id} className="mb-1 opacity-90 hover:opacity-100">
              <span className="text-neutral-500 mr-2">[{new Date(t.timestamp).toLocaleTimeString()}]</span>
              <span className="text-cyan-400">&gt; </span>
              {t.text}
            </div>
          ))
        )}
        {isLive && displayThoughts.length > 0 && (
          <div className="mt-1 animate-pulse">
            <span className="text-cyan-400">&gt; </span>_
          </div>
        )}
      </div>
    </div>
  )
}

export default function LiveStream() {
  return <LiveStreamPanel />
}
