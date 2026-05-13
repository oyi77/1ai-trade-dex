import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchTradingWallets,
  fetchWalletAllocations,
  updateTradingWallet,
  updateWalletAllocation,
} from '../../api'

export function WalletMatrix() {
  const queryClient = useQueryClient()
  const { data: walletsData, isLoading: walletsLoading } = useQuery({ queryKey: ['trading-wallets'], queryFn: fetchTradingWallets })
  const { data: allocationsData, isLoading: allocationsLoading } = useQuery({ queryKey: ['wallet-allocations'], queryFn: fetchWalletAllocations })
  const wallets = walletsData?.items ?? []
  const allocations = allocationsData?.items ?? []

  const toggleWallet = useMutation({
    mutationFn: ({ id, enabled }: { id: number, enabled: boolean }) => updateTradingWallet(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trading-wallets'] })
  })

  const updateAlloc = useMutation({
    mutationFn: ({ id, weight }: { id: number, weight: number }) => updateWalletAllocation(id, { weight }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['wallet-allocations'] })
  })

  if (walletsLoading || allocationsLoading) return <div>Loading Wallets...</div>

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
        <h3 className="text-sm font-medium text-gray-800">Trading Wallets Matrix</h3>
      </div>
      <div className="p-4 overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Wallet / Strategy</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
              {['btc_oracle', 'market_maker', 'line_movement_detector'].map(strategy => (
                <th key={strategy} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{strategy}</th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {wallets.map(wallet => (
              <tr key={wallet.id}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900">
                  {wallet.label} {wallet.is_paper && <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">Paper</span>}
                  <div className="text-xs text-gray-500 font-mono">{wallet.address.slice(0,6)}...{wallet.address.slice(-4)}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                   <button
                    onClick={() => toggleWallet.mutate({ id: wallet.id, enabled: !wallet.enabled })}
                    className={`relative inline-flex flex-shrink-0 h-5 w-9 border-2 border-transparent rounded-full cursor-pointer transition-colors ease-in-out duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 ${wallet.enabled ? 'bg-green-500' : 'bg-gray-200'}`}
                  >
                    <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform ring-0 transition ease-in-out duration-200 ${wallet.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                  </button>
                </td>
                {['btc_oracle', 'market_maker', 'line_movement_detector'].map(strategy => {
                  const alloc = allocations.find(a => a.wallet_id === wallet.id && a.strategy_name === strategy)
                  return (
                    <td key={strategy} className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                      {alloc ? (
                        <div className="flex items-center space-x-2">
                          <input 
                            type="number" 
                            className="w-16 text-sm border-gray-300 rounded-md" 
                            defaultValue={alloc.weight}
                            onBlur={(e) => {
                              const val = parseFloat(e.target.value)
                              if (!isNaN(val) && val !== alloc.weight) {
                                updateAlloc.mutate({ id: alloc.id, weight: val })
                              }
                            }}
                          />
                        </div>
                      ) : (
                        <span className="text-gray-300">-</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
