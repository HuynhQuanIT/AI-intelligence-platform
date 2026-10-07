import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Agent, DocumentRow, Metrics, PlatformData, SecurityEvent, TraceRow } from '../types';

// Nạp số liệu dùng chung (metrics, agents, tài liệu, traces, sự kiện bảo mật).
export function usePlatformData(): PlatformData & { err: string } {
  const [metrics, setMetrics] = useState<Metrics>({});
  const [agents, setAgents] = useState<Agent[]>([]);
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [traces, setTraces] = useState<TraceRow[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [err, setErr] = useState('');

  async function refresh() {
    try {
      const [m, a, d, t, e] = await Promise.all([
        api('/metrics'),
        api('/agents'),
        api('/documents'),
        api('/traces'),
        api('/security/events'),
      ]);

      setMetrics(m);
      setAgents(a);
      setDocs(d);
      setTraces(t);
      setEvents(e);
      setErr('');
    } catch (error: any) {
      setErr('Backend connection failed: ' + error.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return { metrics, agents, docs, traces, events, err, setErr, refresh };
}
