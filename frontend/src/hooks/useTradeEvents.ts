import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api'
import { getCsrfToken } from '../utils/auth'

export type TradeEvent = {
  type: 'trade_opened' | 'trade_settled' | 'signal_found' | 'connected'
  timestamp: string
  data: Record<string, unknown>
}

export function useTradeEvents(onEvent: (event: TradeEvent) => void) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  // Use ref to track last-known token; only update state when it actually changes
  const csrfRef = useRef(getCsrfToken())
  const [csrfToken, setCsrfToken] = useState(csrfRef.current)

  // Poll for key changes (e.g. user logs in/out in another tab or on the admin page)
  useEffect(() => {
    const interval = setInterval(() => {
      const current = getCsrfToken()
      if (csrfRef.current !== current) {
        csrfRef.current = current
        setCsrfToken(current)
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    let es: EventSource | null = null
    let reconnectTimeout: ReturnType<typeof setTimeout>

    const connect = () => {
      es = new EventSource(`${API_BASE}/api/v1/events/stream`, { withCredentials: true })

      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as TradeEvent
          onEventRef.current(event)
        } catch {
          // ignore malformed events
        }
      }

      es.onerror = () => {
        // Prevent rapid reconnect spam which causes ERR_QUIC_PROTOCOL_ERROR / TOO_MANY_RTOS
        if (es) {
          es.close()
          es = null
        }
        reconnectTimeout = setTimeout(() => {
          connect()
        }, 5000) // Backoff 5s
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimeout)
      if (es) es.close()
    }
  }, [csrfToken])
}
