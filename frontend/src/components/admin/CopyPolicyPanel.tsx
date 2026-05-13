import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchCopyPolicies, updateCopyPolicy } from '../../api'

export function CopyPolicyPanel() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['copy-policies'], queryFn: fetchCopyPolicies })
  const policies = data?.items ?? []

  const togglePolicy = useMutation({
    mutationFn: ({ id, enabled }: { id: number, enabled: boolean }) => updateCopyPolicy(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['copy-policies'] })
  })

  if (isLoading) return <div>Loading Copy Policies...</div>

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
        <h3 className="text-sm font-medium text-gray-800">Copy-Trade Policies</h3>
      </div>
      <div className="p-4 overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Source</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Max Size (USD)</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Scale Factor</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Max Delay (s)</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {policies.map(policy => (
              <tr key={policy.id}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900">{policy.source_name}</td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                  <button
                    onClick={() => togglePolicy.mutate({ id: policy.id, enabled: !policy.enabled })}
                    className={`relative inline-flex flex-shrink-0 h-5 w-9 border-2 border-transparent rounded-full cursor-pointer transition-colors ease-in-out duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 ${policy.enabled ? 'bg-green-500' : 'bg-gray-200'}`}
                  >
                    <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform ring-0 transition ease-in-out duration-200 ${policy.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                  </button>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">${policy.max_size_usd}</td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{policy.size_scale_factor}x</td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{policy.max_delay_seconds}</td>
              </tr>
            ))}
            {policies.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-center text-sm text-gray-500">No copy policies configured.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
