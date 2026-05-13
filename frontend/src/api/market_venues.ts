import { api } from '../api'

export interface ProviderManifest {
  name: string
  display_name: string
  version: string
  tags: string[]
}

export interface AIProvider extends ProviderManifest {
  cost_per_1k_tokens_usd: number
  max_tokens: number
  supports_streaming: boolean
  supports_tool_use: boolean
}

export interface AIProviderDetails extends AIProvider {
  description: string
  required_env_vars: string[]
  enabled: boolean
  healthy: boolean
}

export interface MarketProvider extends ProviderManifest {
  venue_type: string
  capabilities: string[]
  supported_currencies: string[]
  is_live_venue: boolean
  supports_paper_mode: boolean
  min_order_size_usd: number
  maker_fee_bps: number
  taker_fee_bps: number
}

export interface MarketProviderDetails extends MarketProvider {
  required_env_vars: string[]
  enabled: boolean
  healthy: boolean
}

export interface DataSource extends ProviderManifest {
  data_types: string[]
  supports_streaming: boolean
  supports_backfill: boolean
  is_live: boolean
  rate_limit_per_minute: number
}

export interface DataSourceDetails extends DataSource {
  required_env_vars: string[]
  enabled: boolean
  healthy: boolean
}

export const marketVenuesAPI = {
  list: () => api.get<{ providers: MarketProvider[] }>('/providers').then(r => r.data.providers),
  get: (name: string) => api.get<MarketProviderDetails>(`/providers/${name}`).then(r => r.data),
  getBalance: (name: string) => api.get<unknown>(`/providers/${name}/balance`).then(r => r.data),
  getPositions: (name: string) => api.get<unknown>(`/providers/${name}/positions`).then(r => r.data),
  getMarkets: (name: string) => api.get<unknown>(`/providers/${name}/markets`).then(r => r.data),
  enable: (name: string) => api.post<{ status: string; name: string }>(`/providers/${name}/enable`).then(r => r.data),
  disable: (name: string) => api.post<{ status: string; name: string }>(`/providers/${name}/disable`).then(r => r.data),
}
