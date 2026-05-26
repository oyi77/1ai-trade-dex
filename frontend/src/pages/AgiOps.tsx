import { Link } from 'react-router-dom'
import { BrainCircuit, ArrowLeft } from 'lucide-react'

import { ModificationEngineVisualizer } from '../components/agi-ops/ModificationEngineVisualizer'
import { BrainGraphExpanded } from '../components/agi-ops/BrainGraphExpanded'
import { PerformanceAttributionChart } from '../components/agi-ops/PerformanceAttributionChart'
import { ExecutionSandboxTab } from '../components/agi-ops/ExecutionSandboxTab'

export default function AgiOps() {
  return (
    <div className="min-h-screen bg-[#050914] text-slate-200 font-sans selection:bg-indigo-500/30 flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-[#0a0f1c]/90 backdrop-blur-md border-b border-indigo-500/20 px-6 py-4 flex items-center justify-between shadow-[0_4px_30px_rgba(0,0,0,0.5)]">
        <div className="flex items-center space-x-4">
          <Link to="/dashboard" className="p-2 hover:bg-slate-800 rounded-full transition-colors group">
            <ArrowLeft className="w-5 h-5 text-slate-400 group-hover:text-indigo-400" />
          </Link>
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <BrainCircuit className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-purple-400">
                AGI Orchestration
              </h1>
              <p className="text-xs text-slate-400 font-medium tracking-wide uppercase">Ops Command Center</p>
            </div>
          </div>
        </div>
        
        <div className="flex items-center space-x-3">
          <div className="px-3 py-1.5 bg-indigo-500/10 border border-indigo-500/20 rounded-md flex items-center">
            <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse mr-2" />
            <span className="text-sm font-medium text-indigo-300">Autonomy Level: MAX</span>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <main className="flex-1 p-6 h-[calc(100vh-80px)]">
        <div className="grid grid-cols-12 grid-rows-2 gap-6 h-full">
          {/* Top Left: Brain Graph */}
          <div className="col-span-12 lg:col-span-7 row-span-1">
            <BrainGraphExpanded />
          </div>

          {/* Top Right: Modification Engine */}
          <div className="col-span-12 lg:col-span-5 row-span-1">
            <ModificationEngineVisualizer />
          </div>

          {/* Bottom Left: Performance Attribution */}
          <div className="col-span-12 lg:col-span-5 row-span-1">
            <PerformanceAttributionChart />
          </div>

          {/* Bottom Right: Execution Sandbox */}
          <div className="col-span-12 lg:col-span-7 row-span-1">
            <ExecutionSandboxTab />
          </div>
        </div>
      </main>
    </div>
  )
}
