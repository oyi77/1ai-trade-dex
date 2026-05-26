import { Code, FileCode, Zap, Clock } from 'lucide-react'
import { motion } from 'framer-motion'

export function ModificationEngineVisualizer() {
  const modifications = [
    {
      id: 'mod-1',
      file: 'backend/strategies/arb_strategy.py',
      time: '2 mins ago',
      agent: 'GPT-4o',
      status: 'success',
      diff: `+ def calculate_spread():\n+     return ask - bid\n- def calculate_spread():\n-     pass`
    },
    {
      id: 'mod-2',
      file: 'backend/config.py',
      time: '1 hour ago',
      agent: 'Claude-3.5-Sonnet',
      status: 'success',
      diff: `+ ENABLE_HFT = True\n- ENABLE_HFT = False`
    }
  ]

  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 overflow-hidden shadow-2xl">
      <div className="p-4 border-b border-slate-800 bg-slate-900/80 backdrop-blur-md flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <Code className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white tracking-wide">Modification Engine</h2>
            <p className="text-xs text-slate-400">Real-time LLM Code Generation</p>
          </div>
        </div>
        <div className="flex items-center space-x-2 px-3 py-1 bg-green-500/10 rounded-full border border-green-500/20">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs font-medium text-green-400">Monitoring Active</span>
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {modifications.map((mod) => (
          <motion.div 
            key={mod.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden group hover:border-blue-500/30 transition-colors"
          >
            <div className="px-4 py-3 border-b border-slate-700/50 flex justify-between items-center bg-slate-800/80">
              <div className="flex items-center space-x-3">
                <FileCode className="w-4 h-4 text-slate-400" />
                <span className="text-sm font-mono text-slate-300">{mod.file}</span>
              </div>
              <div className="flex items-center space-x-4 text-xs text-slate-400">
                <span className="flex items-center"><Zap className="w-3 h-3 mr-1 text-yellow-400" /> {mod.agent}</span>
                <span className="flex items-center"><Clock className="w-3 h-3 mr-1" /> {mod.time}</span>
              </div>
            </div>
            <div className="p-4 font-mono text-sm bg-[#0d1117] overflow-x-auto">
              {mod.diff.split('\n').map((line, i) => (
                <div key={i} className={`whitespace-pre ${line.startsWith('+') ? 'text-green-400 bg-green-400/10' : line.startsWith('-') ? 'text-red-400 bg-red-400/10' : 'text-slate-300'}`}>
                  {line}
                </div>
              ))}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
