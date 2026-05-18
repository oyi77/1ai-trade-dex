import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { StrategyProposal } from '../types/features'
import { retryFetch } from '../utils/retryFetch'
import { API_BASE } from '../api'

export function useProposals() {
  const queryClient = useQueryClient()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['proposals'],
    queryFn: async () => {
      const response = await retryFetch(`${API_BASE}/api/v1/proposals`)
      if (!response.ok) {
        throw new Error('Failed to fetch proposals')
      }
      return response.json() as Promise<StrategyProposal[]>
    },
  })

  const approveMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await retryFetch(`${API_BASE}/api/v1/proposals/${id}/approve`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error('Failed to approve proposal')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposals'] })
    },
  })

  const rejectMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await retryFetch(`${API_BASE}/api/v1/proposals/${id}/reject`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error('Failed to reject proposal')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposals'] })
    },
  })

  return {
    proposals: data || [],
    loading: isLoading,
    error,
    refetch,
    approve: (id: number) => approveMutation.mutate(id),
    reject: (id: number) => rejectMutation.mutate(id),
  }
}
