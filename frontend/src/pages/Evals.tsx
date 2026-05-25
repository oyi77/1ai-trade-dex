import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { fetchEvalReports, fetchEvalReport } from '../api'
import type { EvalReportSummary } from '../types'

function ScoreBadge({ score, threshold }: { score?: number | null; threshold?: number }) {
  if (score == null) return <span className="text-neutral-500">—</span>
  const ok = threshold != null ? score >= threshold : score >= 0.7
  return (
    <span className={`text-xs font-mono font-semibold px-1.5 py-0.5 rounded ${
      ok ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
    }`}>
      {(score * 100).toFixed(1)}%
    </span>
  )
}

function PassBadge({ passed }: { passed: boolean | null }) {
  if (passed === null) return <span className="text-neutral-500">—</span>
  return (
    <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
      passed ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
    }`}>
      {passed ? 'PASS' : 'FAIL'}
    </span>
  )
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="bg-neutral-900 text-xs text-green-300 p-3 rounded overflow-x-auto max-h-96 overflow-y-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export function Evals() {
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const [showJson, setShowJson] = useState(false)

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ['eval-reports'],
    queryFn: fetchEvalReports,
    refetchInterval: 60_000,
  })

  const { data: detailData, isLoading: detailLoading } = useQuery({
    queryKey: ['eval-report', selectedFilename],
    queryFn: () => fetchEvalReport(selectedFilename!),
    enabled: !!selectedFilename,
  })

  const reports = listData?.reports ?? []

  // Group reports by benchmark type
  const grouped = reports.reduce<Record<string, EvalReportSummary[]>>((acc, r) => {
    const key = r.benchmark_type
    if (!acc[key]) acc[key] = []
    acc[key].push(r)
    return acc
  }, {})

  const benchmarkLabels: Record<string, string> = {
    agi_score: 'AGI Score',
    causal_reasoning: 'Causal Reasoning',
    cross_domain_transfer: 'Cross-Domain Transfer',
    few_shot_learning: 'Few-Shot Learning',
    certification_checklist: 'Certification Checklist',
  }

  return (
    <div className="p-6 space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-neutral-800 rounded-lg p-6"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">AGI Evaluations</h2>
          <span className="text-xs text-neutral-500">{reports.length} reports</span>
        </div>

        {listLoading ? (
          <p className="text-neutral-400">Loading reports...</p>
        ) : reports.length === 0 ? (
          <p className="text-neutral-400">No eval reports found. Run the certification checklist first.</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 mb-6">
            {Object.entries(grouped).map(([type, rs]) => {
              const latest = rs[0]
              return (
                <div key={type} className="bg-neutral-700/50 rounded p-3">
                  <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">
                    {benchmarkLabels[type] ?? type}
                  </p>
                  <p className="text-lg font-bold">
                    {latest.score != null ? `${(latest.score * 100).toFixed(1)}%` : '—'}
                  </p>
                  <p className="text-xs text-neutral-500 mt-1">{rs.length} runs</p>
                </div>
              )
            })}
          </div>
        )}
      </motion.div>

      {/* Report list */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="bg-neutral-800 rounded-lg p-6"
      >
        <h3 className="text-lg font-bold mb-4">All Reports</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-neutral-400 text-xs uppercase tracking-wide border-b border-neutral-700">
                <th className="pb-2 pr-4">Date</th>
                <th className="pb-2 pr-4">Benchmark</th>
                <th className="pb-2 pr-4">Score</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2">File</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-700">
              {reports.map((r) => (
                <tr
                  key={r.filename}
                  className={`text-neutral-300 hover:bg-neutral-700/30 transition-colors cursor-pointer ${
                    selectedFilename === r.filename ? 'bg-neutral-700/50' : ''
                  }`}
                  onClick={() => setSelectedFilename(r.filename)}
                >
                  <td className="py-2 pr-4 text-xs text-neutral-400 whitespace-nowrap">
                    {r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}
                  </td>
                  <td className="py-2 pr-4">
                    <span className="text-xs font-medium">{benchmarkLabels[r.benchmark_type] ?? r.benchmark_type}</span>
                  </td>
                  <td className="py-2 pr-4">
                    <ScoreBadge score={r.score} />
                  </td>
                  <td className="py-2 pr-4">
                    {r.certification_eligible != null ? (
                      <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                        r.certification_eligible ? 'bg-green-900/50 text-green-400' : 'bg-amber-900/50 text-amber-400'
                      }`}>
                        {r.certification_eligible ? 'CERTIFIED' : 'PENDING'}
                      </span>
                    ) : (
                      <PassBadge passed={r.passed} />
                    )}
                  </td>
                  <td className="py-2 text-xs text-neutral-500 font-mono truncate max-w-48">
                    {r.filename}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </motion.div>

      {/* Detail panel */}
      <AnimatePresence>
        {selectedFilename && (
          <motion.div
            key="detail"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="bg-neutral-800 rounded-lg p-6"
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold truncate mr-4">{selectedFilename}</h3>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setShowJson(!showJson)}
                  className="text-xs px-2 py-1 rounded bg-neutral-700 hover:bg-neutral-600 text-neutral-300 transition-colors"
                >
                  {showJson ? 'Summary' : 'Raw JSON'}
                </button>
                <button
                  onClick={() => setSelectedFilename(null)}
                  className="text-xs px-2 py-1 rounded bg-neutral-700 hover:bg-neutral-600 text-neutral-300 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>

            {detailLoading ? (
              <p className="text-neutral-400">Loading detail...</p>
            ) : detailData ? (
              showJson ? (
                <JsonBlock data={detailData} />
              ) : (
                <div className="space-y-4">
                  {/* Summary header */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="bg-neutral-700/50 rounded p-3">
                      <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">Score</p>
                      <p className="text-lg font-bold">
                        {detailData.score != null ? `${(detailData.score * 100).toFixed(2)}%` : '—'}
                      </p>
                    </div>
                    <div className="bg-neutral-700/50 rounded p-3">
                      <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">Status</p>
                      <PassBadge passed={detailData.passed} />
                    </div>
                    {detailData.certification_eligible != null && (
                      <div className="bg-neutral-700/50 rounded p-3">
                        <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">Certification</p>
                        <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                          detailData.certification_eligible ? 'bg-green-900/50 text-green-400' : 'bg-amber-900/50 text-amber-400'
                        }`}>
                          {detailData.certification_eligible ? 'ELIGIBLE' : 'NOT ELIGIBLE'}
                        </span>
                      </div>
                    )}
                    <div className="bg-neutral-700/50 rounded p-3">
                      <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">Benchmark</p>
                      <p className="text-sm font-mono text-neutral-200">{detailData.benchmark_id}</p>
                    </div>
                  </div>

                  {/* Timestamp */}
                  {detailData.timestamp && (
                    <div className="text-xs text-neutral-500">
                      {new Date(detailData.timestamp).toLocaleString()}
                    </div>
                  )}

                  {/* Passed / failed benchmarks (for certification checklist) */}
                  {detailData.passed_benchmarks && detailData.passed_benchmarks.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-green-400 mb-2">Passed Benchmarks</h4>
                      <div className="flex flex-wrap gap-2">
                        {detailData.passed_benchmarks.map((b) => (
                          <span key={b} className="text-xs bg-green-900/30 text-green-400 px-2 py-0.5 rounded">{b}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {detailData.failed_benchmarks && detailData.failed_benchmarks.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-red-400 mb-2">Failed Benchmarks</h4>
                      <div className="flex flex-wrap gap-2">
                        {detailData.failed_benchmarks.map((b) => (
                          <span key={b} className="text-xs bg-red-900/30 text-red-400 px-2 py-0.5 rounded">{b}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Benchmark thresholds */}
                  {detailData.benchmark_thresholds && (
                    <div>
                      <h4 className="text-sm font-semibold text-neutral-300 mb-2">Thresholds</h4>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        {Object.entries(detailData.benchmark_thresholds).map(([key, val]) => (
                          <div key={key} className="bg-neutral-700/30 rounded p-2">
                            <p className="text-xs text-neutral-400">{key}</p>
                            <ScoreBadge score={val} />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Metadata / details breakdown */}
                  {detailData.metadata && (
                    <div>
                      <h4 className="text-sm font-semibold text-neutral-300 mb-2">Metadata</h4>
                      <JsonBlock data={detailData.metadata} />
                    </div>
                  )}
                  {detailData.details && (
                    <div>
                      <h4 className="text-sm font-semibold text-neutral-300 mb-2">Details</h4>
                      <JsonBlock data={detailData.details} />
                    </div>
                  )}
                </div>
              )
            ) : (
              <p className="text-red-400">Failed to load report detail.</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
