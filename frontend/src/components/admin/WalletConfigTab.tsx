import { POLL } from '../../polling'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchWalletConfigs,
  createWalletConfig,
  updateWalletConfig,
  deleteWalletConfig,
  createWallet,
  getActiveWallet,
  getWalletBalance,
  setActiveWallet,
  type CreatedWallet,
  type WalletBalance,
} from '../../api'

import { WalletMatrix } from './WalletMatrix'
import { CopyPolicyPanel } from './CopyPolicyPanel'
import { ProviderStatusPanel } from './ProviderStatusPanel'

export function WalletConfigTab() {
  const qc = useQueryClient()
  const [address, setAddress] = useState('')
  const [pseudonym, setPseudonym] = useState('')
  const [adding, setAdding] = useState(false)

  const [creating, setCreating] = useState(false)
  const [createdWallet, setCreatedWallet] = useState<CreatedWallet | null>(null)
  const [copiedKey, setCopiedKey] = useState(false)

  // Active wallet state
  const { data: activeWalletData } = useQuery({
    queryKey: ['wallets-active'],
    queryFn: () => getActiveWallet(),
    refetchInterval: POLL.SLOW,
  })
  const activeWallet = activeWalletData?.active_wallet ?? null

  const { data: configs, isLoading } = useQuery({
    queryKey: ['wallet-configs'],
    queryFn: () => fetchWalletConfigs(),
  })

  const items = configs?.items ?? []
  const total = configs?.total ?? 0

  // Fetch balance for active wallet
  const { data: activeWalletBalance } = useQuery<WalletBalance | null>({
    queryKey: ['wallet-balance', activeWallet],
    queryFn: () => activeWallet ? getWalletBalance(activeWallet) : null,
    refetchInterval: POLL.SLOW,
    enabled: !!activeWallet,
  })

  const handleToggle = async (id: number, enabled: boolean) => {
    await updateWalletConfig(id, { enabled: !enabled })
    qc.invalidateQueries({ queryKey: ['wallet-configs'] })
  }

  const handleDelete = async (id: number) => {
    await deleteWalletConfig(id)
    qc.invalidateQueries({ queryKey: ['wallet-configs'] })
  }

  const handleTrack = async () => {
    if (!address.trim()) return
    setAdding(true)
    try {
      await createWalletConfig({ address: address.trim(), pseudonym: pseudonym.trim() || undefined })
      setAddress('')
      setPseudonym('')
      qc.invalidateQueries({ queryKey: ['wallet-configs'] })
    } finally {
      setAdding(false)
    }
  }

  const handleCreateFresh = async () => {
    setCreating(true)
    setCreatedWallet(null)
    try {
      const wallet = await createWallet()
      setCreatedWallet(wallet)
    } catch (err) {
      console.error('Failed to create wallet:', err)
    } finally {
      setCreating(false)
    }
  }

  const handleCopyKey = () => {
    if (createdWallet) {
      navigator.clipboard.writeText(createdWallet.private_key)
      setCopiedKey(true)
      setTimeout(() => setCopiedKey(false), 2000)
    }
  }

  const handleSetActive = async (address: string) => {
    await setActiveWallet(address)
    qc.invalidateQueries({ queryKey: ['wallets-active'] })
  }

  const handleRefreshBalance = async () => {
    if (activeWallet) {
      // Force refresh from Polymarket API
      await getWalletBalance(activeWallet, true)
      qc.invalidateQueries({ queryKey: ['wallet-balance'] })
    }
  }

  const truncate = (addr: string) =>
    addr.length > 16 ? `${addr.slice(0, 8)}…${addr.slice(-6)}` : addr

  if (isLoading) return <div className="text-[10px] text-neutral-600">Loading wallet configs...</div>

  return (
    <div className="space-y-4">
      <ProviderStatusPanel />
      <WalletMatrix />
      <CopyPolicyPanel />
      
      <div className="text-[10px] text-neutral-500 uppercase tracking-wider mt-12 pt-8 border-t border-neutral-800">
        Legacy Wallet Config — {total} total
      </div>
      <div className="border border-neutral-800 overflow-x-auto">
        <table className="w-full text-[10px] font-mono min-w-[400px]">
          <thead>
            <tr className="border-b border-neutral-800">
              <th className="text-left px-3 py-1.5 text-neutral-600 uppercase tracking-wider">Address</th>
              <th className="text-left px-3 py-1.5 text-neutral-600 uppercase tracking-wider">Pseudonym</th>
              <th className="text-left px-3 py-1.5 text-neutral-600 uppercase tracking-wider">Source</th>
              <th className="text-left px-3 py-1.5 text-neutral-600 uppercase tracking-wider">Enabled</th>
              <th className="px-3 py-1.5"></th>
            </tr>
          </thead>
          <tbody>
            {items.map(row => (
              <tr key={row.id} className="border-b border-neutral-800/50 hover:bg-neutral-900/30">
                <td className="px-3 py-1.5 text-neutral-300" title={row.address}>{truncate(row.address)}</td>
                <td className="px-3 py-1.5 text-neutral-400">{row.pseudonym || '—'}</td>
                <td className="px-3 py-1.5 text-neutral-500">{row.source || '—'}</td>
                <td className="px-3 py-1.5">
                  <button
                    onClick={() => handleToggle(row.id, row.enabled)}
                    className={`text-[9px] uppercase tracking-wider transition-colors ${
                      row.enabled ? 'text-green-500 hover:text-green-400' : 'text-neutral-600 hover:text-neutral-400'
                    }`}
                  >
                    {row.enabled ? 'yes' : 'no'}
                  </button>
                </td>
                <td className="px-3 py-1.5 text-right">
                  <button
                    onClick={() => handleDelete(row.id)}
                    className="text-red-600 hover:text-red-400 transition-colors text-[11px] leading-none"
                    title="Delete"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-3 text-neutral-700 text-center">No wallets configured</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Track Existing Wallet */}
      <div className="border border-neutral-800 p-3">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Track Existing Wallet</div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={address}
            onChange={e => setAddress(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleTrack()}
            placeholder="0x address"
            className="bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none w-full sm:w-64 placeholder:text-neutral-700"
          />
          <input
            type="text"
            value={pseudonym}
            onChange={e => setPseudonym(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleTrack()}
            placeholder="Pseudonym (optional)"
            className="bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none w-full sm:w-48 placeholder:text-neutral-700"
          />
          <button
            onClick={handleTrack}
            disabled={adding || !address.trim()}
            className="px-3 py-1 bg-neutral-800 border border-neutral-700 text-neutral-300 text-[10px] uppercase tracking-wider hover:border-neutral-500 transition-colors disabled:opacity-40"
          >
            {adding ? 'Tracking...' : 'Track'}
          </button>
        </div>
      </div>

      {/* Active Wallet Switcher */}
      <div className="border border-neutral-800 p-3 bg-neutral-900/20">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider">Active Trading Wallet</div>
          {activeWallet && (
            <button
              onClick={() => handleSetActive('')}
              className="text-[9px] text-amber-400 hover:text-amber-300 transition-colors"
            >
              Clear Active
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-neutral-600">Select:</span>
          <select
            value={activeWallet || ''}
            onChange={e => handleSetActive(e.target.value)}
            className="bg-black border border-neutral-700 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-green-500/40 focus:outline-none flex-1"
          >
            <option value="">None selected</option>
            {items.map(item => (
              <option key={item.id} value={item.address}>
                {item.pseudonym || item.address.slice(0, 8)}... {item.pseudonym && ` (${item.pseudonym})`}
              </option>
            ))}
          </select>
          {activeWallet && (
            <button
              onClick={handleRefreshBalance}
              className="text-[9px] text-neutral-400 hover:text-neutral-300 transition-colors"
              title="Refresh balance"
            >
              ↻
            </button>
          )}
        </div>
      </div>

      {/* Active Wallet Balance Display */}
      {activeWallet && (
        <div className="border border-neutral-800 p-3 bg-neutral-900/20">
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Active Wallet Balance</div>
          {activeWalletBalance ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-neutral-600">Address:</span>
                <span className="text-[11px] font-mono text-neutral-300">{truncate(activeWallet)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-neutral-600">USDC Balance:</span>
                <div className="flex items-center gap-2">
                  <span className={`text-[11px] font-bold ${
                    activeWalletBalance.usdc_balance > 0 ? 'text-green-400' : 'text-neutral-500'
                  }`}>
                    ${activeWalletBalance.usdc_balance?.toFixed(2) || '0.00'}
                  </span>
                  <span className="text-[9px] text-neutral-500">
                    {activeWalletBalance.source === 'cache' && 'cached'}
                    {activeWalletBalance.source === 'polymarket' && 'live'}
                    {activeWalletBalance.source === 'error' && 'error'}
                  </span>
                  <span className="text-[9px] text-neutral-700 ml-2">
                    {activeWalletBalance.last_updated ? new Date(activeWalletBalance.last_updated).toLocaleTimeString() : 'N/A'}
                  </span>
                </div>
              </div>
              <div className="text-[10px] text-neutral-700 mt-2">
                <span className="text-neutral-500">Auto-refresh every 30s</span>
              </div>
            </div>
          ) : (
            <div className="text-[10px] text-neutral-600 p-2">
              Select an active wallet above to see balance.
            </div>
          )}
        </div>
      )}

      {/* Create Fresh Wallet */}
      <div className="border border-neutral-800 p-3 bg-neutral-900/20">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Create Fresh Wallet</div>
        <p className="text-[11px] text-neutral-600 mb-4 leading-relaxed">
          Generate a new wallet with private key for Polymarket trading.
          <span className="text-red-400">Save the private key securely — never share it or commit to a repo.</span>
        </p>
        <button
          onClick={handleCreateFresh}
          disabled={creating}
          className="px-3 py-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[10px] uppercase tracking-wider hover:bg-green-500/20 transition-colors disabled:opacity-40"
        >
          {creating ? 'Generating...' : 'Generate New Wallet'}
        </button>
      </div>

      {/* Fresh Wallet Result Modal */}
      {createdWallet && (
        <div className="border border-red-900/50 bg-red-950/10 p-4">
          <div className="text-[10px] text-red-400 uppercase tracking-wider mb-2">Wallet Created — Save This Key Securely</div>
          <div className="space-y-3">
            <div>
              <span className="text-[10px] text-neutral-600">Address:</span>
              <span className="text-[11px] font-mono text-neutral-300 ml-2">{truncate(createdWallet.address)}</span>
            </div>
            <div>
              <span className="text-[10px] text-neutral-600">Private Key:</span>
              <div className="flex items-center gap-2 ml-2">
                <span className="text-[11px] font-mono text-amber-400 break-all">{createdWallet.private_key}</span>
                <button
                  onClick={handleCopyKey}
                  className="px-2 py-0.5 bg-neutral-800 border border-neutral-700 text-neutral-300 text-[9px] uppercase tracking-wider hover:border-neutral-500 transition-colors"
                >
                  {copiedKey ? 'Copied!' : 'Copy'}
                </button>
                <button
                  onClick={() => setCreatedWallet(null)}
                  className="px-2 py-0.5 bg-neutral-800 border border-neutral-700 text-neutral-300 text-[9px] uppercase tracking-wider hover:border-neutral-500 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
            <div className="text-[9px] text-neutral-700 mt-3">
              Use this key in your .env file as <span className="font-mono text-neutral-500">POLYMARKET_PRIVATE_KEY</span>
              or store in your password manager.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
