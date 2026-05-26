import { useState } from 'react'
import { Terminal, Bug, ShieldAlert } from 'lucide-react'
import { motion } from 'framer-motion'

export function ExecutionSandboxTab() {
  const [activeTab, setActiveTab] = useState<'sandbox' | 'logs' | 'prompts'>('sandbox')

  const logs = [
    { time: '15:42:01', level: 'INFO', msg: '[CodeGenerator] Generating backend/strategies/arb.py via groq...' },
    { time: '15:42:05', level: 'DEBUG', msg: 'Validating AST tree for generated code...' },
    { time: '15:42:06', level: 'SUCCESS', msg: 'AST Validation passed. Pushing to Sandbox context.' },
    { time: '15:42:10', level: 'WARN', msg: '[Sandbox] Trade execution simulated. PnL: +$1.20 (Slippage high)' },
  ]

  return (
    <div className="flex flex-col h-full bg-[#0d1117] rounded-xl border border-slate-700/50 overflow-hidden shadow-2xl">
      <div className="flex items-center space-x-1 p-2 bg-slate-900 border-b border-slate-800">
        <button 
          onClick={() => setActiveTab('sandbox')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center ${activeTab === 'sandbox' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}`}
        >
          <ShieldAlert className="w-4 h-4 mr-2" />
          Sandbox Status
        </button>
        <button 
          onClick={() => setActiveTab('logs')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center ${activeTab === 'logs' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}`}
        >
          <Terminal className="w-4 h-4 mr-2" />
          Live Logs
        </button>
        <button 
          onClick={() => setActiveTab('prompts')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center ${activeTab === 'prompts' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}`}
        >
          <Bug className="w-4 h-4 mr-2" />
          Prompt Debugging
        </button>
      </div>

      <div className="flex-1 p-4 overflow-y-auto font-mono text-sm">
        {activeTab === 'logs' && (
          <div className="space-y-2">
            {logs.map((log, i) => (
              <motion.div 
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.1 }}
                key={i} 
                className="flex items-start"
              >
                <span className="text-slate-500 mr-3">[{log.time}]</span>
                <span className={`mr-3 font-semibold ${
                  log.level === 'INFO' ? 'text-blue-400' :
                  log.level === 'SUCCESS' ? 'text-green-400' :
                  log.level === 'WARN' ? 'text-yellow-400' : 'text-purple-400'
                }`}>
                  {log.level}
                </span>
                <span className="text-slate-300">{log.msg}</span>
              </motion.div>
            ))}
            <div className="flex items-center text-slate-500 mt-4 animate-pulse">
              <span className="mr-2">_</span>
              Waiting for new logs...
            </div>
          </div>
        )}

        {activeTab === 'sandbox' && (
          <div className="h-full flex items-center justify-center text-slate-500 flex-col">
            <ShieldAlert className="w-16 h-16 text-slate-700 mb-4" />
            <p className="text-lg">Sandbox Environment Active</p>
            <p className="text-xs mt-2 text-slate-600">No dangerous code detected in last 24h.</p>
          </div>
        )}

        {activeTab === 'prompts' && (
          <div className="h-full flex items-center justify-center text-slate-500 flex-col">
            <Bug className="w-16 h-16 text-slate-700 mb-4" />
            <p className="text-lg">Prompt Traces Empty</p>
            <p className="text-xs mt-2 text-slate-600">Waiting for LLMRouter invocation...</p>
          </div>
        )}
      </div>
    </div>
  )
}
