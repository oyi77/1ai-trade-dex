import { useQuery } from '@tanstack/react-query'
import type { MiroFishSignal } from '../types/features'
import { retryFetch } from '../utils/retryFetch'
import { API_BASE } from '../api'
import { POLL } from '../polling'

export function useMiroFish() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['mirofish-signals'],
    queryFn: async () => {
      const response = await retryFetch(`${API_BASE}/api/v1/signals`)
      if (!response.ok) {
        throw new Error('Failed to fetch MiroFish signals')
      }
      return response.json() as Promise<MiroFishSignal[]>
    },
    refetchInterval: POLL.NORMAL,
  })

  return {
    signals: data || [],
    loading: isLoading,
    error,
    refetch,
  }
}
