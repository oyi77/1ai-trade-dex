import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { Terminal, Bug, ShieldAlert, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'

interface SandboxLog {
  time: string
  level: string
  msg: string
}

interface PromptTrace {
  id: number
  agent: string
  prompt: string
  response: string
  time: string
}

interface SandboxStatus {
  active: boolean
  message: string
  details: string
}

interface SandboxLogsResponse {
  logs: SandboxLog[]
  prompts: PromptTrace[]
  sandbox_status: SandboxStatus
}

export function ExecutionSandboxTab() {
  const [activeTab, setActiveTab] = useState<'sandbox' | 'logs' | 'prompts'>('sandbox')

  const { data, isLoading } = useQuery<SandboxLogsResponse>({
    queryKey: ['agi-sandbox-logs'],
    queryFn: async () => {
      const res = await api.get('/agi/sandbox-logs')
      return res.data
    },
    refetchInterval: 10000,
  })

  if (isLoading || !data) {
    return (
      <div className="flex flex-col h-full bg-[#0d1117] rounded-xl border border-slate-700/50 overflow-hidden shadow-2xl items-center justify-center p-6 text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin mb-2 text-blue-500" />
        <span className="text-sm">Loading sandbox telemetry...</span>
      </div>
    )
  }

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
            {data.logs.map((log, i) => (
              <motion.div 
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
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
          <div className="h-full flex items-center justify-center text-slate-500 flex-col p-4 text-center">
            <ShieldAlert className="w-16 h-16 text-indigo-400 mb-4" />
            <p className="text-lg text-slate-300 font-semibold">{data.sandbox_status.message}</p>
            <p className="text-xs mt-2 text-slate-500">{data.sandbox_status.details}</p>
          </div>
        )}

        {activeTab === 'prompts' && (
          <div className="space-y-4">
            {data.prompts.map((trace) => (
              <motion.div 
                key={trace.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="bg-slate-900 border border-slate-800 rounded p-3 text-xs space-y-2"
              >
                <div className="flex justify-between items-center text-slate-400 pb-1 border-b border-slate-850">
                  <span className="font-semibold text-blue-400 font-mono">{trace.agent}</span>
                  <span>{trace.time}</span>
                </div>
                <div className="space-y-1">
                  <div className="text-slate-400"><span className="text-amber-500 font-semibold font-mono">Prompt:</span> {trace.prompt}</div>
                  <div className="text-slate-300"><span className="text-emerald-500 font-semibold font-mono">Response:</span> {trace.response}</div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
