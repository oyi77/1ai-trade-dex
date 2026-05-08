import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { useBrainGraph } from '../hooks/useBrainGraph'
import { Brain, TrendingUp, Zap, Target, Activity, AlertCircle } from 'lucide-react'

const nodeIcons: Record<string, any> = {
  signal: TrendingUp,
  ai: Brain,
  execution: Target,
  analysis: Activity,
}

const nodeColors: Record<string, { bg: string; border: string; text: string }> = {
  active: { bg: 'bg-green-500/20', border: 'border-green-500', text: 'text-green-400' },
  idle: { bg: 'bg-neutral-800', border: 'border-neutral-700', text: 'text-neutral-500' },
  processing: { bg: 'bg-yellow-500/20', border: 'border-yellow-500', text: 'text-yellow-400' },
  error: { bg: 'bg-red-500/20', border: 'border-red-500', text: 'text-red-400' },
}

const typeColors: Record<string, string> = {
  signal: '#3b82f6',
  ai: '#a855f7',
  execution: '#22c55e',
  analysis: '#f97316',
}

interface GraphNode {
  id: string
  label: string
  type: 'signal' | 'ai' | 'execution' | 'analysis'
  status: 'active' | 'idle' | 'processing' | 'error'
  x: number
  y: number
}

interface GraphEdge {
  id: string
  source: string
  target: string
  label?: string
}

const NODES: GraphNode[] = [
  { id: 'mirofish', label: 'MiroFish', type: 'ai', status: 'active', x: 400, y: 40 },
  { id: 'btc_momentum', label: 'BTC Momentum', type: 'signal', status: 'idle', x: 60, y: 180 },
  { id: 'btc_oracle', label: 'BTC Oracle', type: 'signal', status: 'idle', x: 210, y: 180 },
  { id: 'weather_emos', label: 'Weather EMOS', type: 'signal', status: 'idle', x: 360, y: 180 },
  { id: 'copy_trader', label: 'Copy Trader', type: 'signal', status: 'idle', x: 510, y: 180 },
  { id: 'market_maker', label: 'Market Maker', type: 'signal', status: 'idle', x: 660, y: 180 },
  { id: 'kalshi_arb', label: 'Kalshi Arb', type: 'signal', status: 'idle', x: 60, y: 300 },
  { id: 'bond_scanner', label: 'Bond Scanner', type: 'signal', status: 'idle', x: 210, y: 300 },
  { id: 'whale_pnl', label: 'Whale PNL', type: 'signal', status: 'idle', x: 360, y: 300 },
  { id: 'realtime_scanner', label: 'Realtime Scanner', type: 'signal', status: 'idle', x: 510, y: 300 },
  { id: 'bull', label: 'Bull Agent', type: 'ai', status: 'idle', x: 160, y: 430 },
  { id: 'bear', label: 'Bear Agent', type: 'ai', status: 'idle', x: 400, y: 430 },
  { id: 'judge', label: 'Judge Agent', type: 'ai', status: 'idle', x: 640, y: 430 },
  { id: 'risk_manager', label: 'Risk Manager', type: 'analysis', status: 'idle', x: 280, y: 560 },
  { id: 'proposal_gen', label: 'Proposal Gen', type: 'analysis', status: 'idle', x: 520, y: 560 },
  { id: 'trade_executor', label: 'Trade Executor', type: 'execution', status: 'idle', x: 280, y: 690 },
  { id: 'trade_analyzer', label: 'Trade Analyzer', type: 'analysis', status: 'idle', x: 520, y: 690 },
]

const EDGES: GraphEdge[] = [
  { id: 'e-mirofish-signals', source: 'mirofish', target: 'btc_momentum' },
  { id: 'e-mirofish-btc_oracle', source: 'mirofish', target: 'btc_oracle' },
  { id: 'e-mirofish-weather', source: 'mirofish', target: 'weather_emos' },
  { id: 'e-mirofish-copy', source: 'mirofish', target: 'copy_trader' },
  { id: 'e-mirofish-mm', source: 'mirofish', target: 'market_maker' },
  { id: 'e-mirofish-kalshi', source: 'mirofish', target: 'kalshi_arb' },
  { id: 'e-mirofish-bond', source: 'mirofish', target: 'bond_scanner' },
  { id: 'e-mirofish-whale', source: 'mirofish', target: 'whale_pnl' },
  { id: 'e-mirofish-rt', source: 'mirofish', target: 'realtime_scanner' },
  { id: 'e-btc_momentum-bull', source: 'btc_momentum', target: 'bull' },
  { id: 'e-btc_oracle-bull', source: 'btc_oracle', target: 'bull' },
  { id: 'e-weather_emos-bull', source: 'weather_emos', target: 'bull' },
  { id: 'e-copy_trader-bear', source: 'copy_trader', target: 'bear' },
  { id: 'e-market_maker-bear', source: 'market_maker', target: 'bear' },
  { id: 'e-kalshi_arb-bear', source: 'kalshi_arb', target: 'bear' },
  { id: 'e-bond_scanner-judge', source: 'bond_scanner', target: 'judge' },
  { id: 'e-whale_pnl-judge', source: 'whale_pnl', target: 'judge' },
  { id: 'e-realtime_scanner-judge', source: 'realtime_scanner', target: 'judge' },
  { id: 'e-bull-risk', source: 'bull', target: 'risk_manager' },
  { id: 'e-bear-risk', source: 'bear', target: 'risk_manager' },
  { id: 'e-judge-risk', source: 'judge', target: 'risk_manager' },
  { id: 'e-risk-proposal', source: 'risk_manager', target: 'proposal_gen' },
  { id: 'e-proposal-executor', source: 'proposal_gen', target: 'trade_executor' },
  { id: 'e-executor-analyzer', source: 'trade_executor', target: 'trade_analyzer' },
]

const NODE_W = 140
const NODE_H = 48

function NodeCard({ node }: { node: GraphNode }) {
  const Icon = nodeIcons[node.type] || Activity
  const colors = nodeColors[node.status] || nodeColors.idle

  return (
    <div
      className={`absolute px-3 py-2 rounded-lg border-2 ${colors.bg} ${colors.border} min-w-[${NODE_W}px]`}
      style={{
        left: node.x,
        top: node.y,
        width: NODE_W,
        transform: 'translate(-50%, -50%)',
        zIndex: 10,
      }}
    >
      <div className="flex items-center gap-2">
        <Icon className={`w-3.5 h-3.5 ${colors.text}`} />
        <div className={`text-[10px] font-bold uppercase tracking-wider ${colors.text} truncate`}>
          {node.label}
        </div>
      </div>
      {node.status === 'processing' && (
        <div className="mt-1 h-1 bg-neutral-700 rounded-full overflow-hidden">
          <div className="h-full bg-yellow-500 animate-pulse" style={{ width: '60%' }} />
        </div>
      )}
    </div>
  )
}

export default function BrainGraph() {
  const { graphData, transcript, status, loading } = useBrainGraph()
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)

  const activeNodes = useMemo(() => {
    if (graphData?.nodes) {
      return NODES.map(node => {
        const serverNode = graphData.nodes.find(n => n.id === node.id)
        if (serverNode) {
          return { ...node, status: serverNode.status as GraphNode['status'] }
        }
        return node
      })
    }
    return NODES
  }, [graphData])

  if (loading) {
    return (
      <div className="h-full bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Loading Brain Graph</div>
        </div>
      </div>
    )
  }

  const nodeMap = new Map(activeNodes.map(n => [n.id, n]))

  return (
    <div className="h-full bg-black flex">
      <div className="flex-1 relative overflow-auto">
        <svg
          width={800}
          height={760}
          className="block mx-auto"
          style={{ minWidth: 800 }}
        >
          <defs>
            <marker
              id="arrowhead"
              markerWidth="8"
              markerHeight="6"
              refX="8"
              refY="3"
              orient="auto"
            >
              <polygon points="0 0, 8 3, 0 6" fill="#525252" />
            </marker>
            {['signal', 'ai', 'analysis', 'execution'].map(type => (
              <marker
                key={type}
                id={`arrowhead-${type}`}
                markerWidth="8"
                markerHeight="6"
                refX="8"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill={typeColors[type]} opacity={0.6} />
              </marker>
            ))}
          </defs>
          {EDGES.map(edge => {
            const src = nodeMap.get(edge.source)
            const tgt = nodeMap.get(edge.target)
            if (!src || !tgt) return null

            const x1 = src.x
            const y1 = src.y + NODE_H / 2
            const x2 = tgt.x
            const y2 = tgt.y - NODE_H / 2
            const midY = (y1 + y2) / 2

            const isHighlighted = hoveredNode === edge.source || hoveredNode === edge.target
            const srcType = src.type

            return (
              <path
                key={edge.id}
                d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                fill="none"
                stroke={isHighlighted ? (typeColors[srcType] || '#525252') : '#404040'}
                strokeWidth={isHighlighted ? 2 : 1.5}
                opacity={isHighlighted ? 0.8 : 0.4}
                markerEnd={`url(#arrowhead-${srcType})`}
              />
            )
          })}
        </svg>

        <div className="absolute inset-0 pointer-events-none" style={{ top: 0 }}>
          {activeNodes.map(node => (
            <div
              key={node.id}
              className="pointer-events-auto"
              style={{ position: 'absolute', left: node.x, top: node.y, transform: 'translate(-50%, -50%)', zIndex: 10 }}
              onMouseEnter={() => setHoveredNode(node.id)}
              onMouseLeave={() => setHoveredNode(null)}
            >
              <NodeCard node={node} />
            </div>
          ))}
        </div>

        <div className="absolute top-4 left-4 bg-neutral-900 border border-neutral-800 rounded-lg p-3 z-20">
          <div className="flex items-center gap-2 mb-2">
            <Brain className="w-4 h-4 text-green-500" />
            <span className="text-xs font-bold text-neutral-100 uppercase tracking-wider">Brain Status</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full ${status === 'connected' ? 'bg-green-500' : 'bg-red-400'}`} />
            <span className={`text-[10px] font-mono ${status === 'connected' ? 'text-neutral-400' : 'text-red-400'}`}>
              {status === 'connected' ? 'Connected' : status === 'connecting' ? 'Connecting...' : 'Disconnected'}
            </span>
          </div>
          <div className="mt-2 flex gap-2">
            {Object.entries(typeColors).map(([type, color]) => (
              <div key={type} className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-[9px] text-neutral-500 uppercase">{type}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="w-96 border-l border-neutral-800 bg-neutral-950 flex flex-col">
        <div className="shrink-0 border-b border-neutral-800 p-4">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-green-500" />
            <h2 className="text-sm font-bold text-neutral-100 uppercase tracking-wider">Debate Transcript</h2>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {transcript.length === 0 ? (
            <div className="text-center py-8">
              <AlertCircle className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
              <p className="text-xs text-neutral-600">No active debate</p>
            </div>
          ) : (
            transcript.map((entry, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className="bg-neutral-900 border border-neutral-800 rounded-lg p-3"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-green-400 uppercase tracking-wider">{entry.speaker}</span>
                  <span className="text-[10px] text-neutral-600 font-mono">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <p className="text-xs text-neutral-300 leading-relaxed">{entry.message}</p>
                {entry.vote && (
                  <div className="mt-2 pt-2 border-t border-neutral-800">
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider ${
                        entry.vote === 'approve'
                          ? 'text-green-400'
                          : entry.vote === 'reject'
                          ? 'text-red-400'
                          : 'text-neutral-500'
                      }`}
                    >
                      Vote: {entry.vote}
                    </span>
                  </div>
                )}
              </motion.div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
