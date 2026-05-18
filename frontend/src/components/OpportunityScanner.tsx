import { useEffect, useState } from 'react';
import { api } from '../api';

interface ArbOpportunity {
  market_id: string;
  kind: string;
  net_profit: number;
  yes_price?: number;
  no_price?: number;
}

const REFETCH_INTERVAL = 30_000;

export default function OpportunityScanner() {
  const [items, setItems] = useState<ArbOpportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timerId: ReturnType<typeof setTimeout>;

    const fetch = () => {
      setLoading(true);
      api.get<{ opportunities: ArbOpportunity[] }>('/arbitrage/opportunities')
        .then(r => {
          if (!cancelled) {
            setItems(r.data.opportunities || []);
            setError(false);
          }
        })
        .catch(() => {
          if (!cancelled) setError(true);
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
            timerId = setTimeout(fetch, REFETCH_INTERVAL);
          }
        });
    };

    fetch();
    return () => {
      cancelled = true;
      clearTimeout(timerId);
    };
  }, []);

  return (
    <div className="bg-neutral-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wider mb-3">
        Arbitrage Opportunities
      </h3>

      {loading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-8 bg-neutral-700/50 rounded animate-pulse" />
          ))}
        </div>
      )}

      {!loading && error && (
        <p className="text-red-400 text-sm">Failed to load opportunities</p>
      )}

      {!loading && !error && items.length === 0 && (
        <p className="text-neutral-400 text-sm">No arbitrage opportunities right now.</p>
      )}

      {!loading && !error && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((op, i) => (
            <li
              key={i}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-neutral-900/60 rounded px-3 py-2 text-xs"
            >
              <span className="text-neutral-200 font-medium truncate max-w-[50%]">{op.market_id}</span>
              <span className="text-neutral-500 uppercase">{op.kind}</span>
              <span className={`font-semibold ${(op.net_profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {(op.net_profit ?? 0) >= 0 ? '+' : ''}{((op.net_profit ?? 0) * 100).toFixed(2)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
