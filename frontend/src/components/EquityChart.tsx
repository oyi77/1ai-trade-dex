import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Brush,
} from 'recharts'
import { motion } from 'framer-motion'
import type { EquityPoint } from '../types'

interface Props {
  data: EquityPoint[]
  initialBankroll: number
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload || !payload.length) return null

  const pnlEntry = payload.find((p: any) => p.dataKey === 'pnl')
  const bankrollEntry = payload.find((p: any) => p.dataKey === 'bankroll')

  const pnl = pnlEntry?.value ?? 0
  const bankroll = bankrollEntry?.value ?? 0
  const isPnlPositive = pnl >= 0

  return (
    <div className="bg-neutral-950 border border-neutral-800 px-2 py-1.5 min-w-[110px]">
      <p className="text-[9px] text-neutral-600 mb-1 truncate max-w-[140px]">{label}</p>
      <div className="space-y-0.5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[9px] text-neutral-500">Balance</span>
          <span className="text-[10px] font-semibold tabular-nums text-neutral-200">
            ${bankroll.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="text-[9px] text-neutral-500">P&L</span>
          <span className={`text-[10px] font-semibold tabular-nums ${isPnlPositive ? 'text-green-500' : 'text-red-500'}`}>
            {isPnlPositive ? '+' : ''}${pnl.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  )
}

export function EquityChart({ data, initialBankroll }: Props) {
  if (data.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-neutral-600">
        <p className="text-xs">No trade history</p>
        <p className="text-[10px] mt-0.5">Chart appears after settled trades</p>
      </div>
    )
  }

  const chartData = [
    { timestamp: 'Start', pnl: 0, bankroll: initialBankroll },
    ...data.map(d => ({
      ...d,
      timestamp: new Date(d.timestamp).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }),
    })),
  ]

  const currentPnl = data[data.length - 1]?.pnl ?? 0
  const isPositive = currentPnl >= 0

  let minPnl = 0
  let maxPnl = 0
  let minBankroll = initialBankroll
  let maxBankroll = initialBankroll

  // ⚡ Bolt Performance Optimization:
  // Replacing O(N) chained Math.max/min(...array.map()) with a single O(N) iterator loop
  // prevents "Maximum call stack size exceeded" errors on large datasets
  // and avoids multiple array allocations.
  for (let i = 0; i < data.length; i++) {
    const pnl = data[i].pnl ?? 0
    const bankroll = data[i].bankroll ?? initialBankroll
    if (pnl < minPnl) minPnl = pnl
    if (pnl > maxPnl) maxPnl = pnl
    if (bankroll < minBankroll) minBankroll = bankroll
    if (bankroll > maxBankroll) maxBankroll = bankroll
  }

  const pnlPadding = Math.max(Math.abs(minPnl), Math.abs(maxPnl)) * 0.2 || 1
  const bkPadding = (maxBankroll - minBankroll) * 0.15 || 2

  const brushStart = Math.max(0, chartData.length - 20)

  const gradientId = `equityGradient-${isPositive ? 'green' : 'red'}`

  return (
    <motion.div
      className="h-full"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 5, right: 8, left: -15, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity={0.2} />
              <stop offset="95%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" vertical={false} />

          <XAxis
            dataKey="timestamp"
            stroke="#525252"
            fontSize={9}
            tickLine={false}
            axisLine={false}
            dy={4}
            fontFamily="JetBrains Mono"
            interval="preserveStartEnd"
          />

          <YAxis
            yAxisId="pnl"
            orientation="left"
            stroke="#525252"
            fontSize={9}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `$${v}`}
            domain={[minPnl - pnlPadding, maxPnl + pnlPadding]}
            dx={-5}
            fontFamily="JetBrains Mono"
          />

          <YAxis
            yAxisId="bankroll"
            orientation="right"
            stroke="#404040"
            fontSize={9}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `$${v.toFixed(0)}`}
            domain={[minBankroll - bkPadding, maxBankroll + bkPadding]}
            dx={5}
            fontFamily="JetBrains Mono"
            width={45}
          />

          <Tooltip content={<CustomTooltip />} />

          <ReferenceLine yAxisId="pnl" y={0} stroke="#262626" strokeDasharray="3 3" />

          <Area
            yAxisId="pnl"
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? '#22c55e' : '#ef4444'}
            strokeWidth={1.5}
            fill={`url(#${gradientId})`}
            animationDuration={800}
            dot={false}
          />

          <Line
            yAxisId="bankroll"
            type="monotone"
            dataKey="bankroll"
            stroke="#6366f1"
            strokeWidth={1}
            strokeDasharray="4 2"
            dot={false}
            animationDuration={800}
          />

          <Brush
            dataKey="timestamp"
            height={16}
            stroke="#262626"
            fill="#0a0a0a"
            travellerWidth={5}
            startIndex={brushStart}
            style={{ fontSize: 8 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </motion.div>
  )
}
