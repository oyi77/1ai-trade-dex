import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchTradingWallets,
  fetchWalletAllocations,
  updateTradingWallet,
  updateWalletAllocation,
} from '../../api'

export function WalletMatrix() {
  const queryClient = useQueryClient()
  const [strategies, setStrategies] = useState<string[]>([])
  const [strategiesLoaded, setStrategiesLoaded] = useState(false)
  const { data: walletsData, isLoading: walletsLoading } = useQuery({ queryKey: ['trading-wallets'], queryFn: fetchTradingWallets })
  const { data: allocationsData, isLoading: allocationsLoading } = useQuery({ queryKey: ['wallet-allocations'], queryFn: fetchWalletAllocations })

  useEffect(() => {
    fetch('/api/v1/strategy-config')
      .then(r => r.json())
      .then(data => {
        setStrategies(data.map((s: any) => s.strategy_name))
        setStrategiesLoaded(true)
      })
      .catch(() => setStrategiesLoaded(true))
  }, [])
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

  if (walletsLoading || allocationsLoading || !strategiesLoaded) return <div>Loading Wallets...</div>

  return (
    <div className="bg-neutral-900 rounded-lg shadow-sm border border-neutral-800 overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-900/50 flex justify-between items-center">
        <h3 className="text-sm font-medium text-neutral-100">Trading Wallets Matrix</h3>
      </div>
      <div className="p-4 overflow-x-auto">
        <table className="min-w-full divide-y divide-neutral-800">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Wallet / Strategy</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">Status</th>
              {strategies.map(strategy => (
                <th key={strategy} className="px-3 py-2 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">{strategy}</th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-neutral-900 divide-y divide-neutral-800">
            {wallets.map(wallet => (
              <tr key={wallet.id}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-neutral-100">
                  {wallet.label} {wallet.is_paper && <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-900/30 text-blue-400">Paper</span>}
                  <div className="text-xs text-neutral-500 font-mono">{wallet.address.slice(0,6)}...{wallet.address.slice(-4)}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-neutral-500">
                   <button
                    onClick={() => toggleWallet.mutate({ id: wallet.id, enabled: !wallet.enabled })}
                    className={`relative inline-flex flex-shrink-0 h-5 w-9 border-2 border-transparent rounded-full cursor-pointer transition-colors ease-in-out duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 ${wallet.enabled ? 'bg-green-500' : 'bg-neutral-700'}`}
                  >
                    <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform ring-0 transition ease-in-out duration-200 ${wallet.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                  </button>
                </td>
                {strategies.map(strategy => {
                  const alloc = allocations.find(a => a.wallet_id === wallet.id && a.strategy_name === strategy)
                  return (
                    <td key={strategy} className="px-3 py-2 whitespace-nowrap text-sm text-neutral-500">
                      {alloc ? (
                        <div className="flex items-center space-x-2">
                          <input
                            type="number"
                            className="w-16 text-sm border-neutral-700 bg-neutral-800 text-neutral-300 rounded-md"
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
                        <span className="text-neutral-600">-</span>
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
