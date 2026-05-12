import { useState, useEffect, useRef } from 'react';
import { useSSEEvents } from '../../hooks/useSSEEvents';

type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  logger: string;
  message: string;
  [key: string]: any;
}

export function SystemLogsTab() {
  const [logBuffer, setLogBuffer] = useState<LogEntry[]>([]);
  const [filterLevel, setFilterLevel] = useState<LogLevel | 'ALL'>('INFO');
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Use useSSEEvents with a custom callback to maintain our own buffer
  useSSEEvents({
    channels: ['admin'],
    onEvent: (event) => {
      if (event.event_type === 'system_log' && event.data) {
        const logEntry = event.data as unknown as LogEntry;
        setLogBuffer(prev => [logEntry, ...prev].slice(0, 500));
      }
    }
  });

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = 0;
    }
  }, [logBuffer, autoScroll]);

  const filteredLogs = logBuffer.filter(log => {
    if (filterLevel === 'ALL') return true;
    const levels: LogLevel[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR'];
    const currentMinIdx = levels.indexOf(filterLevel);
    const logIdx = levels.indexOf(log.level);
    return logIdx >= currentMinIdx;
  });

  const getLevelColor = (level: LogLevel) => {
    switch (level) {
      case 'DEBUG': return 'text-neutral-500';
      case 'INFO': return 'text-blue-400';
      case 'WARNING': return 'text-yellow-500';
      case 'ERROR': return 'text-red-500';
      default: return 'text-neutral-300';
    }
  };

  const formatTimestamp = (ts: string) => {
    // Try to extract just the time if it's a full ISO or "YYYY-MM-DD HH:MM:SS,ms"
    if (ts.includes(' ')) {
      const parts = ts.split(' ');
      return parts[1] || ts;
    }
    if (ts.includes('T')) {
      const timePart = ts.split('T')[1];
      return timePart ? timePart.split('.')[0] : ts;
    }
    return ts;
  };

  return (
    <div className="flex flex-col h-[600px] space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider">
          System Logs — {filteredLogs.length} entries {logBuffer.length >= 500 && '(capped)'}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-neutral-600 font-mono">min-level:</span>
            <select
              value={filterLevel}
              onChange={(e) => setFilterLevel(e.target.value as any)}
              className="bg-transparent border border-neutral-800 text-[9px] font-mono px-1 py-0.5 focus:border-neutral-600 focus:outline-none cursor-pointer text-neutral-300"
            >
              <option value="ALL" className="bg-neutral-900">ALL</option>
              <option value="DEBUG" className="bg-neutral-900">DEBUG</option>
              <option value="INFO" className="bg-neutral-900">INFO</option>
              <option value="WARNING" className="bg-neutral-900">WARNING</option>
              <option value="ERROR" className="bg-neutral-900">ERROR</option>
            </select>
          </div>
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`text-[9px] uppercase tracking-wider px-2 py-0.5 border transition-colors ${
              autoScroll ? 'border-blue-900 text-blue-500 bg-blue-500/5' : 'border-neutral-800 text-neutral-600'
            }`}
          >
            {autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
          </button>
          <button
            onClick={() => setLogBuffer([])}
            className="text-[9px] uppercase tracking-wider px-2 py-0.5 border border-neutral-800 text-neutral-600 hover:text-neutral-400 hover:border-neutral-700 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      <div 
        ref={logContainerRef}
        className="flex-1 bg-neutral-950 border border-neutral-800 font-mono text-[10px] overflow-y-auto p-2 space-y-0.5 scrollbar-thin scrollbar-thumb-neutral-800 scrollbar-track-transparent"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-neutral-700 italic">No logs matching filter...</div>
        ) : (
          filteredLogs.map((log, i) => (
            <div key={i} className="flex gap-2 hover:bg-white/5 py-0.5 leading-tight group">
              <span className="text-neutral-600 shrink-0 select-none">[{formatTimestamp(log.timestamp)}]</span>
              <span className={`font-bold shrink-0 w-12 select-none ${getLevelColor(log.level)}`}>{log.level}</span>
              <span className="text-neutral-500 shrink-0 w-32 truncate select-none group-hover:text-neutral-400" title={log.logger}>
                {log.logger.split('.').pop()}
              </span>
              <span className="text-neutral-200 break-all whitespace-pre-wrap">{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
