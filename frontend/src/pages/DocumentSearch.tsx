import { useEffect, useState } from 'react';
import { FileText, Search } from 'lucide-react';
import { api } from '../api/client';
import Panel from '../components/Panel';
import '../components/extras.css';
import type { Group, SearchResponse, SearchSnippet } from '../types';

type Mode = 'hybrid' | 'keyword' | 'semantic';

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: 'hybrid', label: 'Kết hợp', hint: 'Từ khóa và ngữ nghĩa, tốt nhất cho đa số câu hỏi' },
  { id: 'keyword', label: 'Từ khóa', hint: 'Khớp đúng các từ bạn gõ (bỏ qua dấu và chữ hoa/thường)' },
  { id: 'semantic', label: 'Ngữ nghĩa', hint: 'Tìm theo ý nghĩa, kể cả khi tài liệu dùng từ khác' },
];

// Tô sáng các đoạn khớp mà server đã tính sẵn (không dùng innerHTML).
function Snippet({ s }: { s: SearchSnippet }) {
  const parts: (string | JSX.Element)[] = [];
  let at = 0;
  [...s.marks].sort((a, b) => a[0] - b[0]).forEach(([a, b], i) => {
    if (a < at) return;
    if (a > at) parts.push(s.text.slice(at, a));
    parts.push(<mark key={i}>{s.text.slice(a, b)}</mark>);
    at = b;
  });
  if (at < s.text.length) parts.push(s.text.slice(at));
  return (
    <p className="snippet">
      {s.before && '… '}
      {parts}
      {s.after && ' …'}
    </p>
  );
}

type Props = {
  isAdmin: boolean;
  setErr: (message: string) => void;
  onOpenDocument: (documentId: string, chunkIndex?: number | null) => void;
};

export default function DocumentSearch({ isAdmin, setErr, onOpenDocument }: Props) {
  const [q, setQ] = useState('');
  const [mode, setMode] = useState<Mode>('hybrid');
  const [groupId, setGroupId] = useState('');
  const [groups, setGroups] = useState<Group[]>([]);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isAdmin) api('/groups').then(setGroups).catch(() => setGroups([]));
  }, [isAdmin]);

  async function run(event?: React.FormEvent) {
    event?.preventDefault();
    const text = q.trim();
    if (text.length < 2 || busy) return;
    try {
      setBusy(true);
      setErr('');
      const params = new URLSearchParams({ q: text, mode, limit: '10' });
      if (groupId) params.set('group_id', groupId);
      setData(await api('/search?' + params.toString()));
    } catch (error: any) {
      setErr('Tìm kiếm thất bại: ' + error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Panel title="Tìm kiếm tài liệu">
        <form className="search-form" onSubmit={run}>
          <div className="search-box">
            <Search size={18} />
            <input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="Nhập từ khóa hoặc mô tả điều bạn cần tìm, ví dụ: quy trình bảo quản mẫu"
              aria-label="Từ khóa tìm kiếm"
              autoFocus
            />
            <button className="primary" disabled={busy || q.trim().length < 2}>
              {busy ? 'Đang tìm…' : 'Tìm'}
            </button>
          </div>

          <div className="search-options">
            <div className="mode-switch" role="group" aria-label="Chế độ tìm kiếm">
              {MODES.map((m) => (
                <button type="button" key={m.id} title={m.hint}
                  className={mode === m.id ? 'secondary active' : 'secondary'} onClick={() => setMode(m.id)}>
                  {m.label}
                </button>
              ))}
            </div>
            {isAdmin && (
              <select value={groupId} onChange={(event) => setGroupId(event.target.value)} aria-label="Lọc theo nhóm">
                <option value="">Mọi nhóm</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            )}
          </div>
          <p className="note">{MODES.find((m) => m.id === mode)?.hint}.</p>
        </form>
      </Panel>

      {data && (
        <Panel title={`Kết quả (${data.total} tài liệu · ${data.took_ms} ms)`}>
          {data.note && <p className="search-note">{data.note}</p>}
          {data.mode_used !== data.mode && !data.note && (
            <p className="search-note">Đã dùng chế độ: {data.mode_used}.</p>
          )}
          {data.results.length ? data.results.map((doc) => (
            <article className="search-result" key={doc.document_id}>
              <div className="search-head">
                <FileText size={18} />
                <button className="link-title" onClick={() => onOpenDocument(doc.document_id, doc.matches[0]?.chunk_index)}>
                  {doc.title}
                </button>
                {doc.scope === 'group'
                  ? (doc.groups?.length ? doc.groups.map((g) => <span className="chip" key={g.id}>{g.name}</span>)
                      : <span className="chip">Nhóm</span>)
                  : <span className="chip public">Công khai</span>}
                <span className="relevance" title="Mức liên quan so với kết quả tốt nhất">
                  <span style={{ width: Math.max(8, Math.round(doc.relevance * 100)) + '%' }} />
                </span>
              </div>
              {doc.filename && <small className="muted">{doc.filename}</small>}
              {doc.matches.map((m) => (
                <div className="search-match" key={m.chunk_index}>
                  <button className="link-chunk" onClick={() => onOpenDocument(doc.document_id, m.chunk_index)}>
                    Chunk {m.chunk_index}
                    {m.similarity != null && ` · giống ${Math.round(m.similarity * 100)}%`}
                  </button>
                  <Snippet s={m.snippet} />
                </div>
              ))}
            </article>
          )) : (
            <p className="muted">
              Không tìm thấy tài liệu phù hợp. Thử đổi chế độ, dùng từ khóa khác, hoặc bạn chưa có quyền xem tài liệu đó.
            </p>
          )}
        </Panel>
      )}
    </>
  );
}
