import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { Brain, MessageSquare, Network, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'

interface AgentDetail {
  stance: string
  consensus?: string
  args: string
}

interface DebateTopology {
  question: string
  consensus: string
  confidence: string
  market_price: number
  reasoning: string
  agents: {
    Composer: AgentDetail
    Risk: AgentDetail
    Execution: AgentDetail
  }
}

export function BrainGraphExpanded() {
  const [selectedAgent, setSelectedAgent] = useState<'Composer' | 'Risk' | 'Execution'>('Composer')

  const { data, isLoading } = useQuery<DebateTopology>({
    queryKey: ['agi-debate-topology'],
    queryFn: async () => {
      const res = await api.get('/agi/debate-topology')
      return res.data
    },
    refetchInterval: 10000,
  })

  if (isLoading || !data) {
    return (
      <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 shadow-2xl items-center justify-center p-6 text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin mb-2 text-indigo-500" />
        <span className="text-sm">Loading debate topology...</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 shadow-2xl overflow-hidden relative">
      <div className="absolute top-0 left-0 w-full p-4 z-10 flex justify-between items-start pointer-events-none">
        <div className="max-w-[70%]">
          <h2 className="text-lg font-semibold text-white tracking-wide flex items-center">
            <Network className="w-5 h-5 mr-2 text-indigo-400" />
            LLM Debate Topology
          </h2>
          <p className="text-xs text-slate-400 truncate">{data.question}</p>
        </div>
        <div className="bg-indigo-500/10 border border-indigo-500/20 px-3 py-1 rounded-full text-xs text-indigo-300 backdrop-blur-sm pointer-events-auto">
          Consensus: {data.consensus} (Conf: {data.confidence})
        </div>
      </div>

      <div className="flex-1 w-full h-full flex items-center justify-center relative bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-800 via-slate-900 to-[#0d1117]">
        <div className="relative w-64 h-64 -translate-y-4">
          <svg className="absolute inset-0 w-full h-full overflow-visible pointer-events-none">
            <motion.path 
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 2, repeat: Infinity, repeatType: "reverse" }}
              d="M 128 32 L 32 192" 
              stroke="#818cf8" strokeWidth="2" strokeDasharray="4 4" fill="none" className="opacity-50" 
            />
            <motion.path 
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 1.5, repeat: Infinity, repeatType: "reverse", delay: 0.5 }}
              d="M 128 32 L 224 192" 
              stroke="#34d399" strokeWidth="2" fill="none" className="opacity-50" 
            />
            <path d="M 32 192 L 224 192" stroke="#475569" strokeWidth="1" strokeDasharray="2 2" fill="none" />
          </svg>

          <motion.div 
            animate={{ y: [0, -5, 0] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            onClick={() => setSelectedAgent('Composer')}
            className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center cursor-pointer group z-20"
          >
            <div className={`w-16 h-16 rounded-full bg-indigo-500/20 border-2 ${selectedAgent === 'Composer' ? 'border-indigo-400 ring-2 ring-indigo-500/40 shadow-[0_0_15px_rgba(129,140,248,0.6)]' : 'border-indigo-500/60'} flex items-center justify-center transition-all`}>
              <Brain className="w-8 h-8 text-indigo-300" />
            </div>
            <span className="text-xs text-slate-300 mt-2 font-medium bg-slate-800/80 px-2 py-1 rounded-md group-hover:text-indigo-400 transition-colors">StrategyComposer</span>
          </motion.div>

          <motion.div 
            animate={{ y: [0, 3, 0] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut", delay: 1 }}
            onClick={() => setSelectedAgent('Risk')}
            className="absolute bottom-0 left-0 -translate-x-1/2 translate-y-1/2 flex flex-col items-center cursor-pointer group z-20"
          >
            <div className={`w-12 h-12 rounded-full bg-blue-500/20 border-2 ${selectedAgent === 'Risk' ? 'border-blue-400 ring-2 ring-blue-500/40 shadow-[0_0_15px_rgba(59,130,246,0.6)]' : 'border-blue-500/60'} flex items-center justify-center transition-all`}>
              <MessageSquare className="w-5 h-5 text-blue-300" />
            </div>
            <span className="text-xs text-slate-300 mt-2 font-medium bg-slate-800/80 px-2 py-1 rounded-md group-hover:text-blue-400 transition-colors">RiskAgent</span>
          </motion.div>

          <motion.div 
            animate={{ y: [0, 4, 0] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut", delay: 2 }}
            onClick={() => setSelectedAgent('Execution')}
            className="absolute bottom-0 right-0 translate-x-1/2 translate-y-1/2 flex flex-col items-center cursor-pointer group z-20"
          >
            <div className={`w-12 h-12 rounded-full bg-emerald-500/20 border-2 ${selectedAgent === 'Execution' ? 'border-emerald-400 ring-2 ring-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.6)]' : 'border-emerald-500/60'} flex items-center justify-center transition-all`}>
              <MessageSquare className="w-5 h-5 text-emerald-300" />
            </div>
            <span className="text-xs text-slate-300 mt-2 font-medium bg-slate-800/80 px-2 py-1 rounded-md group-hover:text-emerald-400 transition-colors">ExecutionAgent</span>
          </motion.div>
        </div>
      </div>

      <div className="absolute bottom-4 left-4 right-4 bg-slate-950/80 border border-slate-850 p-3 rounded-lg backdrop-blur-sm z-10">
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold text-xs text-indigo-400 font-mono">
            {selectedAgent === 'Composer' ? 'StrategyComposer (Judge)' : selectedAgent === 'Risk' ? 'RiskAgent (Bear)' : 'ExecutionAgent (Bull)'}
          </span>
          <span className="text-[10px] text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded uppercase">
            Stance: {data.agents[selectedAgent].stance}
          </span>
        </div>
        <p className="text-xs text-slate-300 italic">
          &quot;{data.agents[selectedAgent].args}&quot;
        </p>
      </div>
    </div>
  )
}
