import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Activity, Loader2 } from 'lucide-react'

interface AttributionItem {
  name: string
  profit: number
  trades: number
}

interface AttributionResponse {
  providers: AttributionItem[]
  strategies: AttributionItem[]
}

export function PerformanceAttributionChart() {
  const [groupBy, setGroupBy] = useState<'provider' | 'strategy'>('provider')

  const { data, isLoading } = useQuery<AttributionResponse>({
    queryKey: ['agi-performance-attribution'],
    queryFn: async () => {
      const res = await api.get('/agi/performance-attribution')
      return res.data
    },
    refetchInterval: 30000,
  })

  const colors = ['#3b82f6', '#8b5cf6', '#10b981']

  if (isLoading || !data) {
    return (
      <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 shadow-2xl items-center justify-center p-6 text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin mb-2 text-purple-500" />
        <span className="text-sm">Loading attribution data...</span>
      </div>
    )
  }

  const chartData = groupBy === 'provider' ? data.providers : data.strategies

  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 shadow-2xl p-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold text-white tracking-wide flex items-center">
            <Activity className="w-5 h-5 mr-2 text-purple-400" />
            Performance Attribution
          </h2>
          <p className="text-xs text-slate-400">Profitability ROI Grouping</p>
        </div>
        
        <div className="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
          <button
            onClick={() => setGroupBy('provider')}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${groupBy === 'provider' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-400 hover:text-slate-200'}`}
          >
            By LLM Provider
          </button>
          <button
            onClick={() => setGroupBy('strategy')}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${groupBy === 'strategy' ? 'bg-purple-500/20 text-purple-400' : 'text-slate-400 hover:text-slate-200'}`}
          >
            By Strategy
          </button>
        </div>
      </div>

      <div className="flex-1 w-full min-h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `$${val}`} />
            <Tooltip 
              cursor={{ fill: '#1e293b' }}
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px' }}
              itemStyle={{ color: '#e2e8f0' }}
            />
            <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
              {chartData.map((_, index) => (
                <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
