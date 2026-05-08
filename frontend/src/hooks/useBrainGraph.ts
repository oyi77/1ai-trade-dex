import { POLL } from '../polling'
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useWebSocket } from './useWebSocket'
import { getWsUrl, api } from '../api'

export interface BrainNode {
  id: string
  type: 'signal' | 'ai' | 'execution' | 'analysis'
  label: string
  status: 'active' | 'idle' | 'processing' | 'error'
  data?: any
}

export interface BrainEdge {
  id: string
  source: string
  target: string
  animated: boolean
  label?: string
}

export interface BrainGraphData {
  nodes: BrainNode[]
  edges: BrainEdge[]
  debate_id?: string
  timestamp: string
}

export interface DebateTranscript {
  id: string
  timestamp: string
  speaker: string
  message: string
  vote?: 'approve' | 'reject' | 'abstain'
}

export interface UseBrainGraphResult {
  graphData: BrainGraphData | null
  transcript: DebateTranscript[]
  status: 'connecting' | 'connected' | 'disconnected' | 'reconnecting'
  loading: boolean
}

export function useBrainGraph(): UseBrainGraphResult {
  const [graphData, setGraphData] = useState<BrainGraphData | null>(null)
  const [transcript, setTranscript] = useState<DebateTranscript[]>([])
  const [loading, setLoading] = useState(true)

  const wsUrl = useMemo(() => getWsUrl('/ws/brain'), [])
  const { data: wsData, status } = useWebSocket<BrainGraphData>(wsUrl, { topic: 'brain' })

  const { data: restData } = useQuery({
    queryKey: ['brain-status'],
    queryFn: async () => {
      try {
        const res = await api.get('/brain/status')
        return res.data
      } catch {
        return null
      }
    },
    refetchInterval: POLL.NORMAL,
    enabled: status !== 'connected',
  })

  const fetchDebateTranscript = useCallback(async (debateId: string) => {
    try {
      const res = await api.get(`/brain/debate/${debateId}`)
      if (res.status === 200) {
        const data = res.data
        setTranscript(data.transcript || [])
      }
    } catch {
      // Transcript fetch is best-effort
    }
  }, [])

  useEffect(() => {
    if (wsData) {
      setGraphData(wsData)
      setLoading(false)
      if (wsData.debate_id) {
        fetchDebateTranscript(wsData.debate_id)
      }
      return
    }

    if (restData && status !== 'connected') {
      const nodes: BrainNode[] = (restData.strategies || []).map((s: any) => ({
        id: s.id || s.name,
        type: s.type || 'signal',
        label: s.label || s.name,
        status: s.enabled ? 'active' : 'idle',
        data: s,
      }))

      const mirofishNode: BrainNode = {
        id: 'mirofish',
        type: 'ai',
        label: 'MiroFish',
        status: restData.mirofish_enabled ? 'active' : 'idle',
      }

      const allNodes = [mirofishNode, ...nodes]
      const edges: BrainEdge[] = []

      const signals = allNodes.filter((n) => n.type === 'signal')
      const ais = allNodes.filter((n) => n.type === 'ai')
      const analyses = allNodes.filter((n) => n.type === 'analysis')
      const executions = allNodes.filter((n) => n.type === 'execution')

      signals.forEach((s) => {
        ais.forEach((a) => {
          edges.push({
            id: `e-${s.id}-${a.id}`,
            source: s.id,
            target: a.id,
            animated: s.status === 'active',
            label: 'signal',
          })
        })
      })

      ais.forEach((a) => {
        analyses.forEach((an) => {
          edges.push({
            id: `e-${a.id}-${an.id}`,
            source: a.id,
            target: an.id,
            animated: a.status === 'active',
            label: 'analyze',
          })
        })
      })

      analyses.forEach((an) => {
        executions.forEach((e) => {
          edges.push({
            id: `e-${an.id}-${e.id}`,
            source: an.id,
            target: e.id,
            animated: an.status === 'active',
            label: 'execute',
          })
        })
      })

      ais.forEach((a) => {
        if (a.id !== 'mirofish') {
          edges.push({
            id: `e-mirofish-${a.id}`,
            source: 'mirofish',
            target: a.id,
            animated: mirofishNode.status === 'active',
            label: 'validate',
          })
        }
      })

      setGraphData({
        nodes: allNodes,
        edges,
        timestamp: new Date().toISOString(),
      })
      setLoading(false)
    }
  }, [wsData, restData, status, fetchDebateTranscript])

  return {
    graphData,
    transcript,
    status,
    loading,
  }
}
