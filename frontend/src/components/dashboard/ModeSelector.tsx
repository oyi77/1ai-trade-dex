import { useModeFilter } from '../../hooks/useModeFilter'
import type { ModeFilter } from '../../contexts/ModeFilterContext'

const MODES: Array<{ key: ModeFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'paper', label: 'Paper' },
  { key: 'testnet', label: 'Testnet' },
  { key: 'live', label: 'Live' },
]

const MODE_STYLES: Record<ModeFilter, string> = {
  all: 'bg-neutral-500/10 text-neutral-300 border-neutral-500/30',
  paper: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  testnet: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
  live: 'bg-red-500/10 text-red-400 border-red-500/30',
}

export function ModeSelector() {
  const { selectedMode, setSelectedMode } = useModeFilter()

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-neutral-800 bg-black/40">
      <div className="text-[10px] text-neutral-500 uppercase tracking-wider mr-2">
        View:
      </div>
      <div className="flex gap-2">
        {MODES.map(({ key, label }) => {
          const isActive = selectedMode === key
          return (
            <button
              key={key}
              onClick={() => setSelectedMode(key)}
              aria-label={`Filter by ${label} mode`}
              className={`
                px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider
                border rounded transition-all
                ${
                  isActive
                    ? MODE_STYLES[key]
                    : 'border-neutral-700 text-neutral-500 hover:border-neutral-600 hover:text-neutral-400'
                }
              `}
            >
              {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
