import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Agent, DocumentRow, Metrics, PlatformData, Role, SecurityEvent, TraceRow } from '../types';

// Nạp số liệu dùng chung (metrics, agents, tài liệu, traces, sự kiện bảo mật).
// Admin nạp đủ số liệu; user thường chỉ xem được danh sách tài liệu (server từ chối các phần còn lại).
export function usePlatformData(role: Role): PlatformData & { err: string } {
  const [metrics, setMetrics] = useState<Metrics>({});
  const [agents, setAgents] = useState<Agent[]>([]);
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [traces, setTraces] = useState<TraceRow[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [err, setErr] = useState('');

  async function refresh() {
    try {
      if (role !== 'admin') {
        setDocs(await api('/documents'));
        setErr('');
        return;
      }

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
  }, [role]);

  return { metrics, agents, docs, traces, events, err, setErr, refresh };
}
