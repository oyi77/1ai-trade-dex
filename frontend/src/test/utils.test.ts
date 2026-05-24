import { describe, it, expect } from 'vitest'
import { getMarketUrl } from '../utils'

describe('utils', () => {
  describe('getMarketUrl', () => {
    it('returns correct URL for polymarket with eventSlug', () => {
      expect(getMarketUrl('polymarket', 'BTC-USD', 'bitcoin-price')).toBe('https://polymarket.com/event/bitcoin-price')
    })

    it('returns correct URL for polymarket without eventSlug (falls back to ticker)', () => {
      expect(getMarketUrl('polymarket', 'BTC-USD')).toBe('https://polymarket.com/event/BTC-USD')
    })

    it('returns correct URL for kalshi', () => {
      expect(getMarketUrl('kalshi', 'BTC-USD', 'some-slug')).toBe('https://kalshi.com/markets/BTC-USD')
    })

    it('returns # for unknown platforms', () => {
      expect(getMarketUrl('unknown', 'BTC-USD')).toBe('#')
    })
  })
})
