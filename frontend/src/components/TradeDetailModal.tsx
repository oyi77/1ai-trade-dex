import { useState } from 'react'
import type { JournalEntry } from '../types'

interface TradeDetailModalProps {
  entry: JournalEntry
  onClose: () => void
  onSaveNotes: (tradeId: number, notes: string, tags: string[]) => void
}

const RESULT_COLORS: Record<string, string> = {
  win: 'text-green-500 border-green-500/40',
  loss: 'text-red-500 border-red-500/40',
  pending: 'text-yellow-500 border-yellow-500/40',
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9px] text-neutral-600 uppercase tracking-wider">{label}</span>
      <span className="text-[10px] font-mono text-neutral-300">{value ?? '—'}</span>
    </div>
  )
}

export function TradeDetailModal({ entry, onClose, onSaveNotes }: TradeDetailModalProps) {
  const { trade, signal, attempt } = entry
  const [notes, setNotes] = useState(trade.journal_notes ?? '')
  const [tagInput, setTagInput] = useState((trade.journal_tags ?? []).join(', '))
  const [saving, setSaving] = useState(false)

  const resultColor = RESULT_COLORS[trade.result] ?? 'text-neutral-400 border-neutral-700'

  const handleSave = async () => {
    const tags = tagInput.split(',').map(t => t.trim()).filter(Boolean)
    setSaving(true)
    try {
      await onSaveNotes(trade.id, notes, tags)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={onClose}>
      <div
        className="relative w-full max-w-3xl border border-neutral-700 bg-neutral-950 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-neutral-950 border-b border-neutral-800 px-4 py-2 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-mono text-neutral-300">{trade.market_ticker}</span>
            <span className={`text-[9px] uppercase tracking-wider font-bold ${trade.direction === 'up' ? 'text-green-400' : 'text-red-400'}`}>
              {trade.direction?.toUpperCase()}
            </span>
            <span className={`text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 border ${resultColor}`}>
              {trade.result}
            </span>
          </div>
          <button onClick={onClose} className="text-[10px] text-neutral-600 hover:text-neutral-300 transition-colors uppercase tracking-wider">
            Close
          </button>
        </div>

        <div className="p-4 space-y-5">
          {/* Trade metadata grid */}
          <div>
            <span className="text-[9px] text-neutral-600 uppercase tracking-wider block mb-2">Trade Metadata</span>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3">
              <Field label="Entry Price" value={trade.entry_price != null ? `${(trade.entry_price * 100).toFixed(1)}c` : '—'} />
              <Field label="Size" value={trade.size != null ? `$${trade.size.toFixed(2)}` : '—'} />
              <Field label="Filled Size" value={trade.filled_size != null ? `$${trade.filled_size.toFixed(2)}` : '—'} />
              <Field label="Fill Price" value={trade.fill_price != null ? `${(trade.fill_price * 100).toFixed(1)}c` : '—'} />
              <Field label="Fee" value={trade.fee != null ? `$${trade.fee.toFixed(4)}` : '—'} />
              <Field label="Slippage" value={trade.slippage != null ? `${trade.slippage.toFixed(4)}` : '—'} />
              <Field label="Confidence" value={trade.confidence != null ? `${(trade.confidence * 100).toFixed(1)}%` : '—'} />
              <Field label="Edge" value={trade.edge_at_entry != null ? `${(trade.edge_at_entry * 100).toFixed(2)}%` : '—'} />
              <Field label="Model Prob" value={trade.model_probability != null ? `${(trade.model_probability * 100).toFixed(1)}%` : '—'} />
              <Field label="Strategy" value={trade.strategy ?? '—'} />
              <Field label="Mode" value={trade.trading_mode ?? '—'} />
              <Field label="Market Type" value={trade.market_type ?? '—'} />
              <Field label="Timestamp" value={trade.timestamp ? new Date(trade.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'} />
              <Field label="P&L" value={trade.pnl != null ? <span className={trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'}>{trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}</span> : '—'} />
              <Field label="Platform" value={trade.platform} />
              <Field label="Blockchain Verified" value={trade.blockchain_verified ? <span className="text-green-500">Yes</span> : <span className="text-neutral-600">No</span>} />
            </div>
          </div>

          {/* Lifecycle timeline */}
          <div>
            <span className="text-[9px] text-neutral-600 uppercase tracking-wider block mb-2">Trade Lifecycle</span>
            <div className="relative pl-4 border-l border-neutral-800 space-y-4">
              {/* Signal */}
              <div className="relative">
                <div className="absolute -left-[17px] top-1 w-2 h-2 rounded-full bg-blue-500" />
                <div className="space-y-1">
                  <span className="text-[10px] text-blue-400 uppercase tracking-wider font-bold">Signal</span>
                  {signal ? (
                    <div className="space-y-1">
                      {signal.reasoning && (
                        <p className="text-[10px] text-neutral-400">{signal.reasoning}</p>
                      )}
                      {signal.kelly_fraction != null && (
                        <span className="text-[9px] text-neutral-500">Kelly Fraction: <span className="text-neutral-300">{signal.kelly_fraction.toFixed(4)}</span></span>
                      )}
                      {signal.sources && signal.sources.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {signal.sources.map((s, i) => (
                            <span key={i} className="text-[8px] px-1 py-0.5 border border-neutral-700 text-neutral-500">{s}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-[10px] text-neutral-600">No signal data</p>
                  )}
                </div>
              </div>

              {/* Attempt */}
              <div className="relative">
                <div className="absolute -left-[17px] top-1 w-2 h-2 rounded-full bg-yellow-500" />
                <div className="space-y-1">
                  <span className="text-[10px] text-yellow-400 uppercase tracking-wider font-bold">Attempt</span>
                  {attempt ? (
                    <div className="space-y-1">
                      {attempt.reason_code && (
                        <span className="text-[9px] text-neutral-500">Reason: <span className="text-neutral-300">{attempt.reason_code}</span></span>
                      )}
                      {attempt.phase && (
                        <span className="text-[9px] text-neutral-500 ml-2">Phase: <span className="text-neutral-300">{attempt.phase}</span></span>
                      )}
                      {attempt.latency_ms != null && (
                        <span className="text-[9px] text-neutral-500 ml-2">Latency: <span className="text-neutral-300">{attempt.latency_ms}ms</span></span>
                      )}
                      {attempt.factors && (
                        <pre className="text-[10px] font-mono text-neutral-400 bg-black border border-neutral-800 p-2 overflow-x-auto whitespace-pre-wrap break-all mt-1">
                          {JSON.stringify(attempt.factors, null, 2)}
                        </pre>
                      )}
                    </div>
                  ) : (
                    <p className="text-[10px] text-neutral-600">No attempt data</p>
                  )}
                </div>
              </div>

              {/* Execution */}
              <div className="relative">
                <div className="absolute -left-[17px] top-1 w-2 h-2 rounded-full bg-green-500" />
                <div className="space-y-1">
                  <span className="text-[10px] text-green-400 uppercase tracking-wider font-bold">Execution</span>
                  <div className="flex flex-wrap gap-4">
                    <span className="text-[9px] text-neutral-500">Fill Price: <span className="text-neutral-300">{trade.fill_price != null ? `${(trade.fill_price * 100).toFixed(1)}c` : '—'}</span></span>
                    <span className="text-[9px] text-neutral-500">Filled: <span className="text-neutral-300">{trade.filled_size != null ? `$${trade.filled_size.toFixed(2)}` : '—'}</span></span>
                    <span className="text-[9px] text-neutral-500">Fee: <span className="text-neutral-300">{trade.fee != null ? `$${trade.fee.toFixed(4)}` : '—'}</span></span>
                    <span className="text-[9px] text-neutral-500">Slippage: <span className="text-neutral-300">{trade.slippage != null ? trade.slippage.toFixed(4) : '—'}</span></span>
                  </div>
                </div>
              </div>

              {/* Settlement */}
              <div className="relative">
                <div className="absolute -left-[17px] top-1 w-2 h-2 rounded-full bg-purple-500" />
                <div className="space-y-1">
                  <span className="text-[10px] text-purple-400 uppercase tracking-wider font-bold">Settlement</span>
                  <div className="flex flex-wrap gap-4">
                    <span className="text-[9px] text-neutral-500">Result: <span className={trade.result === 'win' ? 'text-green-500' : trade.result === 'loss' ? 'text-red-500' : 'text-yellow-500'}>{trade.result}</span></span>
                    <span className="text-[9px] text-neutral-500">P&L: <span className={trade.pnl != null && trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'}>{trade.pnl != null ? `${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}` : '—'}</span></span>
                    <span className="text-[9px] text-neutral-500">Settled: <span className="text-neutral-300">{trade.settled ? 'Yes' : 'No'}</span></span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* "Why did this trade happen?" section */}
          {(signal?.reasoning || entry.decision?.reasoning) && (
            <div>
              <span className="text-[9px] text-neutral-600 uppercase tracking-wider block mb-2">Why did this trade happen?</span>
              <div className="bg-black border border-neutral-800 p-3">
                <p className="text-[10px] text-neutral-300 leading-relaxed">
                  {signal?.reasoning || entry.decision?.reasoning}
                </p>
              </div>
            </div>
          )}

          {/* Notes section */}
          <div>
            <span className="text-[9px] text-neutral-600 uppercase tracking-wider block mb-2">Journal Notes</span>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Add your notes about this trade..."
              className="w-full h-20 bg-black border border-neutral-800 text-[10px] text-neutral-300 p-2 resize-none focus:outline-none focus:border-neutral-600"
            />
            <div className="flex items-center gap-2 mt-2">
              <input
                type="text"
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                placeholder="Tags (comma separated)"
                className="flex-1 bg-black border border-neutral-800 text-[10px] text-neutral-300 px-2 py-1 focus:outline-none focus:border-neutral-600"
              />
              <button
                onClick={handleSave}
                disabled={saving}
                className="text-[9px] uppercase tracking-wider border border-neutral-700 hover:border-green-500/40 text-neutral-400 hover:text-green-500 px-3 py-1 transition-colors disabled:opacity-40"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
