import { POLL } from '../../polling'
import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { updateCredentials, changeAdminPassword, fetchSystemStatus, toggleTradingMode } from '../../api'
import { useAuth } from '../../hooks/useAuth'

const MODE_META = {
  paper:   { label: 'Paper',   color: 'text-amber-400',  border: 'border-amber-500/30',  desc: 'Simulated orders, no credentials needed' },
  testnet: { label: 'Testnet', color: 'text-yellow-400', border: 'border-yellow-500/30', desc: 'Mainnet CLOB with Builder auth (gasless)' },
  live:    { label: 'Live',    color: 'text-red-400',    border: 'border-red-500/30',    desc: 'Real money on Polygon mainnet' },
} as const

function AdminPasswordSection() {
  const { authRequired, logout } = useAuth()
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null)

  if (!authRequired) return null

  const handleSave = async () => {
    if (!newPw.trim()) return
    if (newPw !== confirmPw) {
      setStatus({ ok: false, message: 'Passwords do not match' })
      return
    }
    setSaving(true)
    setStatus(null)
    try {
      const result = await changeAdminPassword(newPw)
      setStatus({ ok: true, message: result.message })
      setNewPw('')
      setConfirmPw('')
      setTimeout(() => logout(), 1500)
    } catch {
      setStatus({ ok: false, message: 'Failed to change password' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-neutral-800 bg-neutral-900/20 p-4">
      <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Change Admin Password</div>
      <p className="text-[11px] text-neutral-600 mb-4 leading-relaxed">
        Updates <span className="text-neutral-400 font-mono">ADMIN_API_KEY</span> in <span className="text-neutral-400 font-mono">.env</span>. You will be logged out after saving.
      </p>
      <div className="space-y-3">
        <input
          type="password"
          value={newPw}
          onChange={e => setNewPw(e.target.value)}
          placeholder="New password"
          className="w-full bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none placeholder:text-neutral-700"
        />
        <input
          type="password"
          value={confirmPw}
          onChange={e => setConfirmPw(e.target.value)}
          placeholder="Confirm new password"
          className="w-full bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none placeholder:text-neutral-700"
        />
      </div>
      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving || !newPw.trim() || !confirmPw.trim()}
          className="px-3 py-1.5 bg-neutral-800 border border-neutral-700 text-neutral-300 text-[10px] uppercase tracking-wider hover:border-neutral-500 transition-colors disabled:opacity-40"
        >
          {saving ? 'Saving...' : 'Change Password'}
        </button>
        {status && (
          <span className={`text-[10px] font-mono ${status.ok ? 'text-green-500' : 'text-red-500'}`}>
            {status.message}
          </span>
        )}
      </div>
    </div>
  )
}

export function CredentialsTab() {
  const qc = useQueryClient()
  const [privateKey, setPrivateKey] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [apiPassphrase, setApiPassphrase] = useState('')
  const [signatureType, setSignatureType] = useState<number>(0)
  const [builderApiKey, setBuilderApiKey] = useState('')
  const [builderSecret, setBuilderSecret] = useState('')
  const [builderPassphrase, setBuilderPassphrase] = useState('')
  const [relayerApiKey, setRelayerApiKey] = useState('')
  const [relayerAddress, setRelayerAddress] = useState('')
  const [saveStatus, setSaveStatus] = useState<{ ok: boolean; message: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [switchingMode, setSwitchingMode] = useState(false)

  const { data: sysStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['admin-system-creds'],
    queryFn: fetchSystemStatus,
    refetchInterval: POLL.NORMAL,
  })

  const handleSave = async () => {
    const payload: Record<string, string | number> = {}
    if (privateKey.trim()) payload.private_key = privateKey.trim()
    if (apiKey.trim()) payload.api_key = apiKey.trim()
    if (apiSecret.trim()) payload.api_secret = apiSecret.trim()
    if (apiPassphrase.trim()) payload.api_passphrase = apiPassphrase.trim()
    if (signatureType !== (sysStatus?.signature_type ?? 0)) payload.signature_type = signatureType
    if (builderApiKey.trim()) payload.builder_api_key = builderApiKey.trim()
    if (builderSecret.trim()) payload.builder_secret = builderSecret.trim()
    if (builderPassphrase.trim()) payload.builder_passphrase = builderPassphrase.trim()
    if (relayerApiKey.trim()) payload.relayer_api_key = relayerApiKey.trim()
    if (relayerAddress.trim()) payload.relayer_api_key_address = relayerAddress.trim()
    if (!Object.keys(payload).length) return

    setSaving(true)
    setSaveStatus(null)
    try {
      const result = await updateCredentials(payload)
      setSaveStatus({ ok: true, message: `Saved: ${result.updated.map(k => k.replace('POLYMARKET_', '')).join(', ')}` })
      setPrivateKey('')
      setApiKey('')
      setApiSecret('')
      setApiPassphrase('')
      setBuilderApiKey('')
      setBuilderSecret('')
      setBuilderPassphrase('')
      setRelayerApiKey('')
      setRelayerAddress('')
      refetchStatus()
      qc.invalidateQueries({ queryKey: ['admin-system'] })
      qc.invalidateQueries({ queryKey: ['admin-settings'] })
    } catch {
      setSaveStatus({ ok: false, message: 'Failed to save credentials' })
    } finally {
      setSaving(false)
    }
  }

  const handleToggleMode = async (mode: 'paper' | 'testnet' | 'live', active: boolean) => {
    setSwitchingMode(true)
    try {
      await toggleTradingMode(mode, active)
      refetchStatus()
      qc.invalidateQueries({ queryKey: ['admin-system'] })
    } finally {
      setSwitchingMode(false)
    }
  }

  const authFields = [
    { label: 'Private Key',    hint: '0x hex — required for testnet + live', value: privateKey,    setter: setPrivateKey,    badge: 'testnet + live' },
    { label: 'API Key',        hint: 'CLOB API key — required for live only', value: apiKey,        setter: setApiKey,        badge: 'live' },
    { label: 'API Secret',     hint: 'CLOB API secret',                       value: apiSecret,     setter: setApiSecret,     badge: 'live' },
    { label: 'API Passphrase', hint: 'CLOB API passphrase',                   value: apiPassphrase, setter: setApiPassphrase, badge: 'live' },
  ]

  const builderFields = [
    { label: 'Builder API Key',   hint: 'Polymarket Builder Program key', value: builderApiKey,    setter: setBuilderApiKey },
    { label: 'Builder Secret',    hint: 'Builder Program secret',          value: builderSecret,    setter: setBuilderSecret },
    { label: 'Builder Passphrase',hint: 'Builder Program passphrase',      value: builderPassphrase, setter: setBuilderPassphrase },
  ]

  const relayerFields = [
    { label: 'Relayer API Key',  hint: 'Gasless relayer API key',     value: relayerApiKey, setter: setRelayerApiKey },
    { label: 'Relayer Address',   hint: '0x address for relayer auth', value: relayerAddress, setter: setRelayerAddress },
  ]

  const activeModes = new Set(sysStatus?.active_modes ?? [sysStatus?.trading_mode ?? 'paper'])
  const sigTypeLabel = sysStatus?.signature_type_label ?? 'EOA (direct wallet)'
  const builderConfigured = sysStatus?.builder_configured ?? false
  const credsReady = {
    paper:   true,
    testnet: sysStatus?.creds_testnet ?? false,
    live:    sysStatus?.creds_live ?? false,
  }
  const missing = {
    testnet: sysStatus?.missing_for_testnet ?? [],
    live:    sysStatus?.missing_for_live ?? [],
  }

  // Initialize signature type from server once loaded
  useEffect(() => {
    if (sysStatus && signatureType === 0 && sysStatus.signature_type !== 0 && !builderApiKey) {
      setSignatureType(sysStatus.signature_type)
    }
  }, [sysStatus, signatureType, builderApiKey])

  return (
    <div className="space-y-4">
      {/* Mode Switcher */}
      <div className="border border-neutral-800 bg-neutral-900/20 p-4">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-3">Trading Mode</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
          {(['paper', 'testnet', 'live'] as const).map(mode => {
            const meta = MODE_META[mode]
            const ready = credsReady[mode]
            const active = activeModes.has(mode)
            const miss = mode !== 'paper' ? missing[mode] : []
            return (
              <button
                key={mode}
                disabled={switchingMode || (active && activeModes.size <= 1)}
                onClick={() => handleToggleMode(mode, !active)}
                title={miss.length > 0 ? `Missing: ${miss.join(', ')}` : meta.desc}
                className={`relative p-3 border text-left transition-colors disabled:cursor-not-allowed ${
                  active
                    ? `${meta.border} bg-neutral-900`
                    : 'border-neutral-800 hover:border-neutral-600'
                }`}>
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${active ? meta.color : 'text-neutral-500'}`}>
                    {meta.label}
                  </span>
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${ready ? 'bg-green-500' : 'bg-neutral-700'}`} />
                </div>
                <div className="text-[9px] text-neutral-600 leading-tight">{meta.desc}</div>
                {miss.length > 0 && (
                  <div className="text-[8px] text-amber-600/80 mt-1 truncate">
                    Need: {miss.map(k => k.replace('POLYMARKET_', '')).join(', ')}
                  </div>
                )}
                {active && (
                  <div className={`absolute top-1.5 right-1.5 text-[8px] uppercase tracking-wider ${meta.color}`}>active</div>
                )}
              </button>
            )
          })}
        </div>
        {switchingMode && <div className="text-[10px] text-neutral-500">Switching mode...</div>}
      </div>

      {/* Credential form */}
      <div className="border border-neutral-800 bg-neutral-900/20 p-4">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Polymarket Auth</div>
        <p className="text-[11px] text-neutral-600 mb-4 leading-relaxed">
          Persisted to <span className="text-neutral-400 font-mono">.env</span> and hot-reloaded — no restart needed.
          Only fill fields you want to update.
        </p>
        <div className="space-y-3">
          {authFields.map(({ label, hint, value, setter, badge }) => (
            <div key={label}>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] text-neutral-400 uppercase tracking-wider w-36">{label}</span>
                {badge && <span className="text-[9px] text-neutral-600">({badge})</span>}
              </div>
              <input
                type="password"
                value={value}
                onChange={e => setter(e.target.value)}
                placeholder={hint}
                className="w-full bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none placeholder:text-neutral-700"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Signature Type */}
      <div className="border border-neutral-800 bg-neutral-900/20 p-4">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Signature Type</div>
        <p className="text-[11px] text-neutral-600 mb-3 leading-relaxed">
          Required for proxy wallets (email login). <span className="text-neutral-400 font-mono">sig_type=1</span> returns balance for Polymarket proxy wallets.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={signatureType}
            onChange={e => setSignatureType(parseInt(e.target.value, 10))}
            className="bg-neutral-950 border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none"
          >
            <option value={0}>0 — EOA (direct wallet)</option>
            <option value={1}>1 — Poly-Proxy (email login)</option>
            <option value={2}>2 — Poly-EOA (PK → proxy)</option>
          </select>
          <span className="text-[9px] text-neutral-600">Current: {sigTypeLabel}</span>
        </div>
      </div>

      {/* Builder Program */}
      <div className="border border-neutral-800 bg-neutral-900/20 p-4">
        <div className="flex items-center gap-2 mb-1">
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider">Builder Program</div>
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${builderConfigured ? 'bg-green-500' : 'bg-neutral-700'}`} />
        </div>
        <p className="text-[11px] text-neutral-600 mb-4 leading-relaxed">
          Gasless trading via Polymarket Builder Program. Enables testnet mode (mainnet CLOB + Builder auth).
        </p>
        <div className="space-y-3">
          {builderFields.map(({ label, hint, value, setter }) => (
            <div key={label}>
              <div className="text-[10px] text-neutral-400 uppercase tracking-wider mb-1">{label}</div>
              <input
                type="password"
                value={value}
                onChange={e => setter(e.target.value)}
                placeholder={hint}
                className="w-full bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none placeholder:text-neutral-700"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Relayer API */}
      <div className="border border-neutral-800 bg-neutral-900/20 p-4">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Relayer API</div>
        <p className="text-[11px] text-neutral-600 mb-4 leading-relaxed">
          Gasless on-chain operations via Polymarket Relayer.
        </p>
        <div className="space-y-3">
          {relayerFields.map(({ label, hint, value, setter }) => (
            <div key={label}>
              <div className="text-[10px] text-neutral-400 uppercase tracking-wider mb-1">{label}</div>
              <input
                type="password"
                value={value}
                onChange={e => setter(e.target.value)}
                placeholder={hint}
                className="w-full bg-transparent border border-neutral-800 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:border-neutral-600 focus:outline-none placeholder:text-neutral-700"
              />
            </div>
          ))}
        </div>
      </div>

      <AdminPasswordSection />

      {/* Save all credentials */}
      <div className="border border-neutral-800 bg-neutral-900/20 p-4">
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 bg-neutral-800 border border-neutral-700 text-neutral-300 text-[10px] uppercase tracking-wider hover:border-neutral-500 transition-colors disabled:opacity-40"
          >
            {saving ? 'Saving...' : 'Save All Credentials'}
          </button>
          {saveStatus && (
            <span className={`text-[10px] font-mono ${saveStatus.ok ? 'text-green-500' : 'text-red-500'}`}>
              {saveStatus.message}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
