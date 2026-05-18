export function ProviderStatusPanel() {
  // No live provider data available — show placeholder
  const providers: { name: string; status: string }[] = []

  return (
    <div className="bg-neutral-900 rounded-lg shadow-sm border border-neutral-800 overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-900/50 flex justify-between items-center">
        <h3 className="text-sm font-medium text-neutral-100">Market Providers</h3>
      </div>
      <div className="p-4 overflow-x-auto">
        {providers.length === 0 ? (
          <p className="text-neutral-500 text-sm">No provider data available.</p>
        ) : (
          <table className="min-w-full divide-y divide-neutral-800">
            <thead>
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Provider</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Status</th>
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
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
