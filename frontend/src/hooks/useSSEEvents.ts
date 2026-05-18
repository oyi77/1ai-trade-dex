import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../api'

export type SSEEvent = {
  event_type: 'trade_executed' | 'settlement_completed' | 'strategy_health_killed'
    | 'autonomous_promotion' | 'arbitrage_fired' | 'regime_shift'
    | 'chromosome_flagged' | 'strategy_param_mutated' | 'genome_killed'
    | 'genome_promoted' | 'genome_ready_for_paper' | 'lifecycle_transition'
    | 'connected' | 'system_log';
  timestamp: string;
  data?: any;
};

interface UseSSEEventsOptions {
  channels?: string[];
  enabled?: boolean;
  onEvent?: (event: SSEEvent) => void;
}

interface UseSSEEventsResult {
  events: SSEEvent[];
  status: 'connecting' | 'connected' | 'disconnected';
  lastEvent: SSEEvent | null;
}

export function useSSEEvents(options: UseSSEEventsOptions = {}): UseSSEEventsResult {
  const { channels, enabled = true, onEvent } = options;
  const queryClient = useQueryClient();
  
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled) {
      setStatus('disconnected');
      return;
    }

    let es: EventSource | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout>;

    const connect = () => {
      setStatus('connecting');
      
      const params = new URLSearchParams();
      if (channels?.length) params.set('channels', channels.join(','));

      const qs = params.toString();
      const url = `${API_BASE}/api/events/stream${qs ? '?' + qs : ''}`;
      
      es = new EventSource(url, { withCredentials: true });

      es.onopen = () => {
        setStatus('connected');
      };

      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          if (!event.event_type && event.type) {
            event.event_type = event.type;
          }
          
          setEvents(prev => {
            const next = [event as SSEEvent, ...prev];
            return next.slice(0, 50);
          });
          setLastEvent(event);
          
          // Trigger custom callback
          if (onEventRef.current) {
            onEventRef.current(event);
          }

          // React Query invalidations
          switch (event.event_type) {
            case 'trade_executed':
              queryClient.invalidateQueries({ queryKey: ['trades'] });
              queryClient.invalidateQueries({ queryKey: ['stats'] });
              queryClient.invalidateQueries({ queryKey: ['dashboard'] });
              break;
            case 'settlement_completed':
              queryClient.invalidateQueries({ queryKey: ['trades'] });
              queryClient.invalidateQueries({ queryKey: ['stats'] });
              break;
            case 'strategy_health_killed':
              queryClient.invalidateQueries({ queryKey: ['strategies'] });
              queryClient.invalidateQueries({ queryKey: ['stats'] });
              break;
            case 'autonomous_promotion':
              queryClient.invalidateQueries({ queryKey: ['strategies'] });
              queryClient.invalidateQueries({ queryKey: ['experiments'] });
              break;
            case 'regime_shift':
              queryClient.invalidateQueries({ queryKey: ['stats'] });
              break;
          }
        } catch (err) {
          console.error('SSE Parse Error:', err);
        }
      };

      es.onerror = () => {
        if (es) {
          es.close();
          es = null;
        }
        setStatus('disconnected');
        reconnectTimeout = setTimeout(connect, 5000);
      };
    };

    connect();

    return () => {
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (es) es.close();
    };
  }, [channels, enabled, queryClient]);

  return {
    events,
    status,
    lastEvent
  };
}
