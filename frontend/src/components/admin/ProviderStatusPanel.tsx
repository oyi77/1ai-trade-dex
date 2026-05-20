import { useQuery } from "@tanstack/react-query"
import { adminApi } from "../../api"

interface Provider {
  name: string
  display_name: string
  venue_type: string
  status: string
  paper_mode: boolean
  is_live_venue: boolean
  capabilities: string[]
  required_env_vars: string[]
  taker_fee_bps: number
  maker_fee_bps: number
}

export function ProviderStatusPanel() {
  const { data: providers, isLoading } = useQuery<Provider[]>({
    queryKey: ["market-providers"],
    queryFn: async () => {
      const res = await adminApi.get("/api/v1/market-providers")
      return res.data?.providers ?? []
    },
    refetchInterval: 30000,
  })

  return (
    <div className="bg-neutral-900 rounded-lg shadow-sm border border-neutral-800 overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-900/50 flex justify-between items-center">
        <h3 className="text-sm font-medium text-neutral-100">Market Providers</h3>
        <span className="text-xs text-neutral-500">{providers?.length ?? 0} registered</span>
      </div>
      <div className="p-4 overflow-x-auto">
        {isLoading ? (
          <p className="text-neutral-500 text-sm">Loading providers...</p>
        ) : !providers?.length ? (
          <p className="text-neutral-500 text-sm">No providers registered.</p>
        ) : (
          <table className="min-w-full divide-y divide-neutral-800">
            <thead>
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Provider</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Type</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Mode</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Fees (bps)</th>
              </tr>
            </thead>
            <tbody className="bg-neutral-900 divide-y divide-neutral-800">
              {providers.map((p) => (
                <tr key={p.name}>
                  <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-neutral-100">
                    {p.display_name}
                    <span className="ml-1 text-xs text-neutral-500">({p.name})</span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-xs text-neutral-400">{p.venue_type}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${p.status === 'active' ? 'bg-green-900/30 text-green-400' : 'bg-neutral-800 text-neutral-400'}`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-xs">
                    {p.paper_mode ? (
                      <span className="text-yellow-400">Paper</span>
                    ) : p.is_live_venue ? (
                      <span className="text-green-400">Live</span>
                    ) : (
                      <span className="text-neutral-500">N/A</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-xs text-neutral-400">
                    {p.taker_fee_bps > 0 ? `T:${p.taker_fee_bps / 100}%` : ''}
                    {p.taker_fee_bps > 0 && p.maker_fee_bps > 0 ? ' / ' : ''}
                    {p.maker_fee_bps > 0 ? `M:${p.maker_fee_bps / 100}%` : ''}
                    {p.taker_fee_bps === 0 && p.maker_fee_bps === 0 ? 'Free' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
