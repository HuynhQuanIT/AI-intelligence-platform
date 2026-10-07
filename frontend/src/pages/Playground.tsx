import { BrainCircuit, Plus, Send, Trash2 } from 'lucide-react';
import Markdown from '../components/Markdown';
import { useChat } from '../hooks/useChat';
import type { PlatformData } from '../types';

type Props = Pick<PlatformData, 'refresh' | 'setErr'>;

export default function Playground({ refresh, setErr }: Props) {
  const {
    q, setQ, chat, useRag, setUseRag, sending, conversations, activeId, liveStep, messagesRef,
    openConversation, newConversation, removeConversation, send,
  } = useChat({ refresh, setErr });

  return (
    <div className="chat-layout">
      <aside className="conv-list">
        <button className="primary conv-new" onClick={newConversation} disabled={sending}>
          <Plus size={14} /> Chat mới
        </button>

        {!conversations.length && <p className="muted">Chưa có hội thoại nào.</p>}

        {conversations.map((c) => (
          <div key={c.id} className={'conv-item' + (c.id === activeId ? ' active' : '')}>
            <button
              className="conv-open"
              onClick={() => openConversation(c.id)}
              disabled={sending}
              title={c.title}
            >
              <span>{c.title}</span>
              <small>{new Date(c.updated_at).toLocaleString()}</small>
            </button>
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

          <button className="primary" onClick={send} disabled={!q.trim() || sending}>
            <Send size={17} />
          </button>
        </div>

        <small className="muted center">AI can make mistakes. Verify important information.</small>
      </div>
    </div>
  );
}
