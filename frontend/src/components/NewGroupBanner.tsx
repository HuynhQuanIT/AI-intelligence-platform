import { useMemo, useState } from 'react';
import { Users, X } from 'lucide-react';
import type { Access, Page } from '../types';

const KEY = 'aip_seen_groups';
const RECENT_MS = 7 * 24 * 3600 * 1000;

function loadSeen(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]');
  } catch {
    return [];
  }
}

// Báo cho người dùng khi vừa được thêm vào nhóm (trong 7 ngày gần đây), đóng rồi không hiện lại.
export default function NewGroupBanner({ access, onOpen }: { access?: Access; onOpen: (p: Page) => void }) {
  const [seen, setSeen] = useState<string[]>(loadSeen);
  const fresh = useMemo(
    () => (access?.groups ?? []).filter((g) => {
      const t = g.added_at ? Date.parse(g.added_at) : 0;
      return t && Date.now() - t < RECENT_MS && !seen.includes(`${g.id}:${g.added_at}`);
    }),
    [access, seen],
  );
  if (!fresh.length) return null;

  function dismiss() {
    const next = [...seen, ...fresh.map((g) => `${g.id}:${g.added_at}`)].slice(-50);
    setSeen(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* bỏ qua */ }
  }

  const total = fresh.reduce((n, g) => n + g.document_count, 0);
  return (
    <div className="group-banner" aria-label="Thông báo nhóm">
      <Users size={18} />
      <div>
        <b>Bạn vừa được thêm vào nhóm {fresh.map((g) => g.name).join(', ')}.</b>
        <span> {total ? `Bạn xem được thêm ${total} tài liệu của nhóm.` : 'Nhóm chưa có tài liệu riêng.'}</span>
      </div>
      <button className="secondary" onClick={() => { dismiss(); onOpen('My Account'); }}>Xem nhóm của tôi</button>
      <button className="icon-close" onClick={dismiss} aria-label="Đóng"><X size={16} /></button>
    </div>
  );
}
