import { useEffect, useRef, useState, useCallback } from 'react'
import { getWsUrl } from '../api'
import type { ActivityLog } from '../types/features'

type WSStatus = 'connecting' | 'open' | 'closed' | 'error'

export interface UseActivityResult {
  activities: ActivityLog[]
  isConnected: boolean
  error: string | null
}

export function useActivity(): UseActivityResult {
  const [activities, setActivities] = useState<ActivityLog[]>([])
  const [status, setStatus] = useState<WSStatus>('connecting')
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number>(0)
  const closedByUser = useRef(false)

  const connect = useCallback(() => {
    setStatus('connecting')
    setError(null)
    
    try {
      const wsUrl = getWsUrl('/ws/activities')
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        retryRef.current = 0
        setStatus('open')
        setError(null)
      }

      ws.onmessage = (evt) => {
        try {
          const activity = JSON.parse(evt.data) as ActivityLog
          // E-142: Cap activity array to prevent unbounded memory growth
          const MAX_ACTIVITIES = 200
          setActivities((prev) => [activity, ...prev].slice(0, MAX_ACTIVITIES))
        } catch (err) {
          console.error('Failed to parse activity message:', err)
        }
      }

      ws.onerror = () => {
        setStatus('error')
        setError('WebSocket connection error')
      }

      ws.onclose = () => {
        setStatus('closed')
        if (closedByUser.current) return
        
        // Exponential backoff reconnection
        const backoff = Math.min(30000, 1000 * Math.pow(2, retryRef.current))
        retryRef.current += 1
        
        setTimeout(() => {
          if (!closedByUser.current) connect()
        }, backoff)
      }
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : 'Failed to connect')
    }
  }, [])

  useEffect(() => {
    closedByUser.current = false
    connect()
    
    return () => {
      closedByUser.current = true
      wsRef.current?.close()
    }
  }, [connect])

  return {
    activities,
    isConnected: status === 'open',
    error,
  }
}
