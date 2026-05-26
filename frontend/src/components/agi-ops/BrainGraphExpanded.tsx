import { Brain, MessageSquare, Network } from 'lucide-react'
import { motion } from 'framer-motion'

export function BrainGraphExpanded() {
  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 shadow-2xl overflow-hidden relative">
      <div className="absolute top-0 left-0 w-full p-4 z-10 flex justify-between items-start pointer-events-none">
        <div>
          <h2 className="text-lg font-semibold text-white tracking-wide flex items-center">
            <Network className="w-5 h-5 mr-2 text-indigo-400" />
            LLM Debate Topology
          </h2>
          <p className="text-xs text-slate-400">Real-time reasoning paths</p>
        </div>
        <div className="bg-indigo-500/10 border border-indigo-500/20 px-3 py-1 rounded-full text-xs text-indigo-300 backdrop-blur-sm">
          98.5% Consensus
        </div>
      </div>

      <div className="flex-1 w-full h-full flex items-center justify-center relative bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-800 via-slate-900 to-[#0d1117]">
        {/* Mocked Graph nodes */}
        <div className="relative w-64 h-64">
          {/* Edges */}
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

          {/* Orchestrator Node */}
          <motion.div 
            animate={{ y: [0, -10, 0] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center"
          >
            <div className="w-16 h-16 rounded-full bg-indigo-500/20 border-2 border-indigo-400 flex items-center justify-center shadow-[0_0_15px_rgba(129,140,248,0.5)]">
              <Brain className="w-8 h-8 text-indigo-300" />
            </div>
            <span className="text-xs text-slate-300 mt-2 font-medium bg-slate-800/80 px-2 py-1 rounded-md">StrategyComposer</span>
          </motion.div>

          {/* Critic Node 1 */}
          <motion.div 
            animate={{ y: [0, 5, 0] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut", delay: 1 }}
            className="absolute bottom-0 left-0 -translate-x-1/2 translate-y-1/2 flex flex-col items-center"
          >
            <div className="w-12 h-12 rounded-full bg-blue-500/20 border-2 border-blue-400 flex items-center justify-center">
              <MessageSquare className="w-5 h-5 text-blue-300" />
            </div>
            <span className="text-xs text-slate-300 mt-2 font-medium bg-slate-800/80 px-2 py-1 rounded-md">RiskAgent</span>
          </motion.div>

          {/* Critic Node 2 */}
          <motion.div 
            animate={{ y: [0, 8, 0] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut", delay: 2 }}
            className="absolute bottom-0 right-0 translate-x-1/2 translate-y-1/2 flex flex-col items-center"
          >
            <div className="w-12 h-12 rounded-full bg-emerald-500/20 border-2 border-emerald-400 flex items-center justify-center">
              <MessageSquare className="w-5 h-5 text-emerald-300" />
            </div>
            <span className="text-xs text-slate-300 mt-2 font-medium bg-slate-800/80 px-2 py-1 rounded-md">ExecutionAgent</span>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
