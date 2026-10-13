import { useState } from 'react';
import { BrainCircuit, Check, FileText, Pencil, Plus, RotateCw, Send, Square, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import Markdown from '../components/Markdown';
import QuotaBar from '../components/QuotaBar';
import { AccessLine } from '../components/AccessInfo';
import { useChat } from '../hooks/useChat';
import type { PlatformData, SourceRef } from '../types';

type Props = Pick<PlatformData, 'refresh' | 'setErr'> & {
  onOpenDocument: (documentId: string, chunkIndex?: number | null) => void;
};

// Nguồn tài liệu đã dùng để trả lời, gộp theo tài liệu, kèm nhãn Công khai / tên nhóm.
function Sources({ sources, onOpen }: { sources?: SourceRef[]; onOpen: Props['onOpenDocument'] }) {
  if (!sources?.length) return null;
  const byDoc = new Map<string, SourceRef & { chunks: number[] }>();
  for (const s of sources) {
    const key = s.document_id || s.title || String(byDoc.size);
    const cur = byDoc.get(key) ?? { ...s, chunks: [] };
    if (s.chunk_index != null) cur.chunks.push(s.chunk_index);
    byDoc.set(key, cur);
  }
  return (
    <div className="sources">
      <small>Nguồn tham khảo</small>
      {[...byDoc.entries()].map(([key, s]) => (
        <div className="source" key={key} title={(s.snippet || s.content || '').slice(0, 200)}>
          <FileText size={14} />
          {s.document_id ? (
            <button className="link-title" title="Mở đúng đoạn trong Knowledge Center"
              onClick={() => onOpen(s.document_id as string, [...s.chunks].sort((a, b) => a - b)[0])}>
              {s.title || 'Tài liệu'}
            </button>
          ) : <b>{s.title || 'Tài liệu'}</b>}
          {s.chunks.length > 0 && (
            <span className="muted">
              chunk{' '}
              {[...s.chunks].sort((a, b) => a - b).map((c, i) => (
                <button key={c} className="link-chunk" onClick={() => onOpen(s.document_id as string, c)}>
                  {i > 0 ? ', ' : ''}{c}
                </button>
              ))}
            </span>
          )}
          {s.scope === 'group' ? (
            s.groups?.length
              ? s.groups.map((g) => <span className="chip" key={g.id}>{g.name}</span>)
              : <span className="chip">Nhóm</span>
          ) : s.scope === 'public' ? (
            <span className="chip public">Công khai</span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

// Tên hội thoại: bấm bút chì để sửa tại chỗ (Enter lưu, Esc hủy).
function RenameBox({ initial, onSave, onCancel }: { initial: string; onSave: (t: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState(initial);
  return (
    <div className="conv-rename">
      <input autoFocus value={value} maxLength={60} aria-label="Tên hội thoại"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSave(value);
          if (e.key === 'Escape') onCancel();
        }} />
      <button title="Lưu tên" aria-label="Lưu tên" onClick={() => onSave(value)} disabled={!value.trim()}><Check size={13} /></button>
      <button title="Hủy" aria-label="Hủy" onClick={onCancel}><X size={13} /></button>
    </div>
  );
}

export default function Playground({ refresh, setErr, onOpenDocument }: Props) {
  const { user } = useAuth();
  const {
    q, setQ, chat, useRag, setUseRag, sending, conversations, activeId, liveStep, messagesRef,
    openConversation, newConversation, removeConversation, renameConversation, send, stop, regenerate, rate,
  } = useChat({ refresh, setErr });
  const [renaming, setRenaming] = useState<string | null>(null);

  return (
    <div className="chat-layout">
      <aside className="conv-list">
        <button className="primary conv-new" onClick={newConversation} disabled={sending}>
          <Plus size={14} /> Chat mới
        </button>

        {!conversations.length && <p className="muted">Chưa có hội thoại nào.</p>}

        {conversations.map((c) => (
          <div key={c.id} className={'conv-item' + (c.id === activeId ? ' active' : '')}>
            {renaming === c.id ? (
              <RenameBox initial={c.title} onCancel={() => setRenaming(null)}
                onSave={(t) => { setRenaming(null); void renameConversation(c.id, t); }} />
            ) : (
              <>
                <button
                  className="conv-open"
                  onClick={() => openConversation(c.id)}
                  disabled={sending}
                  title={c.title}
                >
                  <span>{c.title}</span>
                  <small>{new Date(c.updated_at).toLocaleString()}</small>
                </button>
                <button className="conv-delete" onClick={() => setRenaming(c.id)} title="Đổi tên hội thoại"
                  aria-label="Đổi tên hội thoại">
                  <Pencil size={13} />
                </button>
              </>
            )}
            <button
              className="conv-delete"
              onClick={() => removeConversation(c.id)}
              disabled={sending}
              title="Xóa hội thoại"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </aside>

      <div className="chat">
        <div className="chathead">
          <div>
            <b>RAG Assistant</b>
            <div className="muted">AI request playground</div>
            <QuotaBar quota={user?.quota} />
            <AccessLine access={user?.access} />
          </div>

          <div className="chat-actions">
            <label className="rag-toggle">
              <input type="checkbox" checked={useRag} onChange={(event) => setUseRag(event.target.checked)} />
              Enable RAG
            </label>
          </div>
        </div>

        <div className="messages" ref={messagesRef}>
          {!chat.length && (
            <div className="welcome">
              <BrainCircuit size={36} />

              <h2>What can I help you explore?</h2>

              <p>
                Ask a question and test your AI workflow.
                {useRag ? ' Knowledge retrieval is enabled.' : ' Knowledge retrieval is disabled.'}
              </p>

              <button onClick={() => setQ('Explain the platform architecture')}>
                Explain the platform architecture →
              </button>
            </div>
          )}

          {chat.map((message, index) => (
            <div className={'bubble ' + message.role} key={index}>
              <small>{message.role === 'user' ? 'YOU' : 'AI ASSISTANT'}</small>

              {message.role === 'user' ? (
                <p>{message.text}</p>
              ) : message.text ? (
                <Markdown text={message.text} />
              ) : (
                <p className="muted">Đang xử lý{liveStep ? ': ' + liveStep : ''}…</p>
              )}

              {message.role === 'ai' && <Sources sources={message.meta?.sources} onOpen={onOpenDocument} />}

              {message.role === 'ai' && message.stopped && <small className="stopped-note">Đã dừng trả lời</small>}

              {message.role === 'ai' && !message.streaming && (
                <div className="msg-actions">
                  {message.id !== undefined && (
                    <>
                      <button className={'icon-btn' + (message.feedback === 1 ? ' on' : '')} aria-pressed={message.feedback === 1}
                        title="Câu trả lời tốt" aria-label="Câu trả lời tốt" onClick={() => rate(index, 1)}>
                        <ThumbsUp size={14} />
                      </button>
                      <button className={'icon-btn down' + (message.feedback === -1 ? ' on' : '')} aria-pressed={message.feedback === -1}
                        title="Câu trả lời chưa tốt" aria-label="Câu trả lời chưa tốt" onClick={() => rate(index, -1)}>
                        <ThumbsDown size={14} />
                      </button>
                    </>
                  )}
                  {index === chat.length - 1 && !sending && (
                    <button className="icon-btn" title="Sinh lại câu trả lời" aria-label="Sinh lại câu trả lời" onClick={regenerate}>
                      <RotateCw size={14} /> Sinh lại
                    </button>
                  )}
                </div>
              )}

              {message.role === 'ai' && message.meta && message.meta.model !== undefined && (
                <small className="message-meta">
                  Model: {message.meta.model || (message.meta.blocked ? 'blocked by Security Agent' : 'unknown')}
                  {' · '}
                  Latency: {message.meta.latency_ms ?? 0} ms
                  {' · '}
                  Tokens: {(message.meta.input_tokens ?? 0) + (message.meta.output_tokens ?? 0)}
                  {' · '}
                  Cost: ${Number(message.meta.cost_usd ?? 0).toFixed(6)}
                </small>
              )}
            </div>
          ))}
        </div>

        <div className="compose">
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder="Message your AI assistant..."
            disabled={sending}
          />

          {sending ? (
            <button className="primary stop-btn" onClick={stop} title="Dừng trả lời" aria-label="Dừng trả lời">
              <Square size={15} /> Dừng
            </button>
          ) : (
            <button className="primary" onClick={() => send()} disabled={!q.trim()} aria-label="Gửi">
              <Send size={17} />
            </button>
          )}
        </div>

        <small className="muted center">AI can make mistakes. Verify important information.</small>
      </div>
    </div>
  );
}
