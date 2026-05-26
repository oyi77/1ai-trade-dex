import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { Code, FileCode, Zap, Clock, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'

interface Modification {
  id: string
  file: string
  time: string
  agent: string
  status: 'success' | 'failed' | 'pending'
  diff: string
}

export function ModificationEngineVisualizer() {
  const { data: modifications = [], isLoading } = useQuery<Modification[]>({
    queryKey: ['agi-modifications'],
    queryFn: async () => {
      const res = await api.get('/agi/modifications')
      return res.data
    },
    refetchInterval: 10000, // Refresh every 10s
  })

  if (isLoading) {
    return (
      <div className="flex flex-col h-full bg-slate-900 rounded-xl border border-slate-700/50 overflow-hidden shadow-2xl items-center justify-center p-6 text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin mb-2 text-blue-500" />
        <span className="text-sm">Loading modifications...</span>
      </div>
    )
  }

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
