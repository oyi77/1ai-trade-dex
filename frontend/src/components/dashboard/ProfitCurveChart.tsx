import { useMemo } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { format } from 'date-fns'

interface ProfitPoint {
  timestamp: string
  cumulative_pnl: number
}

interface ProfitCurveChartProps {
  data: ProfitPoint[]
}

export function ProfitCurveChart({ data }: ProfitCurveChartProps) {
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return []
    return data.map(point => ({
      time: new Date(point.timestamp).getTime(),
      pnl: point.cumulative_pnl,
      label: format(new Date(point.timestamp), 'MMM d'),
    }))
  }, [data])

  const maxPnl = useMemo(() => chartData.reduce((max, d) => Math.max(max, d.pnl), 0), [chartData])
  const minPnl = useMemo(() => chartData.reduce((min, d) => Math.min(min, d.pnl), 0), [chartData])

  if (chartData.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-xs text-neutral-600">No profit data</span>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="profitGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="time"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(ts) => format(new Date(ts), 'MMM d')}
          stroke="#525252"
          tick={{ fill: '#737373', fontSize: 10 }}
          tickLine={false}
        />
        <YAxis
          domain={[minPnl * 1.1, maxPnl * 1.1]}
          stroke="#525252"
          tick={{ fill: '#737373', fontSize: 10 }}
          tickLine={false}
          tickFormatter={(val) => `$${val.toFixed(0)}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#171717',
            border: '1px solid #404040',
            borderRadius: '4px',
            padding: '8px',
          }}
          labelStyle={{ color: '#a3a3a3', fontSize: '10px', marginBottom: '4px' }}
          itemStyle={{ color: '#10b981', fontSize: '11px', fontWeight: 600 }}
          formatter={(value: number) => [`$${value.toFixed(2)}`, 'Profit']}
          labelFormatter={(ts) => format(new Date(ts), 'MMM d, yyyy HH:mm')}
        />
        <Area
          type="monotone"
          dataKey="pnl"
          stroke="#10b981"
          strokeWidth={2}
          fill="url(#profitGradient)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
