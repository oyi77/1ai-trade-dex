import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Activity } from 'lucide-react'

const providerData = [
  { name: 'GPT-4o', profit: 4500, trades: 120 },
  { name: 'Claude-3.5', profit: 3200, trades: 85 },
  { name: 'Groq/Llama3', profit: 1200, trades: 300 },
]

const strategyData = [
  { name: 'Arbitrage', profit: 6000, trades: 450 },
  { name: 'Momentum', profit: 2100, trades: 30 },
  { name: 'Mean Reversion', profit: 800, trades: 25 },
]

export function PerformanceAttributionChart() {
  const [groupBy, setGroupBy] = useState<'provider' | 'strategy'>('provider')

  const data = groupBy === 'provider' ? providerData : strategyData
  const colors = ['#3b82f6', '#8b5cf6', '#10b981']

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
          <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `$${val}`} />
            <Tooltip 
              cursor={{ fill: '#1e293b' }}
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px' }}
              itemStyle={{ color: '#e2e8f0' }}
            />
            <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
              {data.map((_, index) => (
                <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
