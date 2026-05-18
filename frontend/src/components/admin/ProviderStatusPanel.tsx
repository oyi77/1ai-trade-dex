export function ProviderStatusPanel() {
  // Mock data for now since T7/T8 (MarketProviderPlugin) are skipped on this branch
  const providers = [
    { name: 'Polymarket', status: 'active', latency: '120ms', markets_tracked: 420 },
    { name: 'Kalshi', status: 'disabled', latency: '-', markets_tracked: 0 },
  ]

  return (
    <div className="bg-neutral-900 rounded-lg shadow-sm border border-neutral-800 overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-900/50 flex justify-between items-center">
        <h3 className="text-sm font-medium text-neutral-100">Market Providers</h3>
      </div>
      <div className="p-4 overflow-x-auto">
        <table className="min-w-full divide-y divide-neutral-800">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Provider</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Status</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Latency</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Markets Tracked</th>
            </tr>
          </thead>
          <tbody className="bg-neutral-900 divide-y divide-neutral-800">
            {providers.map(provider => (
              <tr key={provider.name}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-neutral-100">{provider.name}</td>
                <td className="px-3 py-2 whitespace-nowrap text-sm">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${provider.status === 'active' ? 'bg-green-900/30 text-green-400' : 'bg-neutral-800 text-neutral-400'}`}>
                    {provider.status}
                  </span>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-neutral-500">{provider.latency}</td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-neutral-500">{provider.markets_tracked}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
