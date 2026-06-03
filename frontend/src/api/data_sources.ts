import { api } from '../api'

export interface DataSource {
  name: string
  display_name: string
  version: string
  data_types: string[]
  supports_streaming: boolean
  supports_backfill: boolean
  is_live: boolean
  rate_limit_per_minute: number
  tags: string[]
}

export interface DataSourceDetails extends DataSource {
  description?: string
  required_env_vars: string[]
  enabled: boolean
  healthy: boolean
}

export interface MarketVenue {
  name: string
  display_name: string
  version: string
  venue_type: string
  capabilities: string[]
  supported_currencies: string[]
  is_live_venue: boolean
  supports_paper_mode: boolean
  min_order_size_usd: number
  maker_fee_bps: number
  taker_fee_bps: number
  tags: string[]
}

export interface MarketVenueDetails extends MarketVenue {
  required_env_vars: string[]
  enabled: boolean
  healthy: boolean
}

export interface VenueBalance {
  total_balance_usd: number
  available_balance_usd: number
  wallet_address?: string
  last_updated: string
}

export interface VenuePosition {
  market_id: string
  market_question?: string
  position_size: number
  entry_price: number
  current_price?: number
  pnl?: number
  status: string
}

export const dataSourcesAPI = {
  list: () => api.get<{ sources: DataSource[] }>('/sources').then(r => r.data.sources),
  get: (name: string) => api.get<DataSourceDetails>(`/sources/${name}`).then(r => r.data),
  enable: (name: string) => api.post<{ status: string; name: string }>(`/sources/${name}/enable`).then(r => r.data),
  disable: (name: string) => api.post<{ status: string; name: string }>(`/sources/${name}/disable`).then(r => r.data),
}