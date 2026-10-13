import { useEffect, useRef, useState } from 'react';
import { api, apiFetch, errorMessageOf } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { readSse } from '../api/sse';
import type { ChatMessage, Conversation, LiveStep } from '../types';

type Options = { refresh: () => Promise<void>; setErr: (message: string) => void };

// Hội thoại + gửi tin nhắn qua SSE cho trang AI Playground.
export function useChat({ refresh, setErr }: Options) {
  const [q, setQ] = useState('');
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [useRag, setUseRag] = useState(true);
  const [sending, setSending] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const { refreshUser } = useAuth(); // nạp lại hạn mức còn lại sau mỗi lượt chat

  useEffect(() => {
    loadConversations();
  }, []);

  // Luôn cuộn xuống tin nhắn mới nhất khi có chữ hiện thêm.
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat]);

  async function loadConversations() {
    try {
      setConversations(await api('/conversations'));
    } catch (error: any) {
      setErr('Không tải được danh sách hội thoại: ' + error.message);
    }
  }

  async function openConversation(id: string) {
    if (sending || id === activeId) return;

    try {
      const rows = await api('/conversations/' + id + '/messages');
      setChat(rows.map((m: any) => ({
        role: m.role, text: m.text, meta: m.meta,
        id: m.role === 'ai' ? m.id : undefined, feedback: m.feedback ?? null,
      })));
      setActiveId(id);
      setErr('');
    } catch (error: any) {
      setErr('Không mở được hội thoại: ' + error.message);
    }
  }

  function newConversation() {
    if (sending) return;
    setActiveId(null);
    setChat([]);
    setErr('');
  }

  async function removeConversation(id: string) {
    if (sending) return;
    if (!window.confirm('Xóa hội thoại này? Không thể hoàn tác.')) return;

    try {
      await api('/conversations/' + id, { method: 'DELETE' });
      if (id === activeId) {
        setActiveId(null);
        setChat([]);
      }
      await loadConversations();
    } catch (error: any) {
      setErr('Không xóa được hội thoại: ' + error.message);
    }
  }

  // Cập nhật tin nhắn AI đang được viết (luôn là tin cuối).
  function patchLast(update: (m: ChatMessage) => ChatMessage) {
    setChat((current) => {
      if (!current.length) return current;
      const copy = current.slice();
      copy[copy.length - 1] = update(copy[copy.length - 1]);
      return copy;
    });
  }

  // Đổi tên hội thoại (đổi ngay trên giao diện, lỗi thì nạp lại danh sách).
  async function renameConversation(id: string, title: string) {
    const name = title.trim();
    if (!name) return;
    try {
      const updated = await api('/conversations/' + id, { method: 'PUT', body: JSON.stringify({ title: name }) });
      setConversations((list) => list.map((c) => (c.id === id ? { ...c, title: updated.title } : c)));
    } catch (error: any) {
      setErr('Không đổi được tên: ' + error.message);
      loadConversations();
    }
  }

  // 👍/👎: bấm lại đúng nút đang chọn thì bỏ đánh giá. Cập nhật ngay, lỗi thì hoàn lại.
  async function rate(index: number, value: 1 | -1) {
    const target = chat[index];
    if (!target?.id) return;
    const next = target.feedback === value ? 0 : value;
    const before = target.feedback ?? null;
    const apply = (feedback: 1 | -1 | null) =>
      setChat((cur) => cur.map((m) => (m.id === target.id ? { ...m, feedback } : m)));
    apply(next === 0 ? null : next);
    try {
      await api('/messages/' + target.id + '/feedback', { method: 'PUT', body: JSON.stringify({ rating: next }) });
    } catch (error: any) {
      apply(before);
      setErr('Không lưu được đánh giá: ' + error.message);
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  // Sinh lại câu trả lời cuối: server xóa lượt hỏi-đáp cuối rồi trả lời lại cùng câu hỏi.
  function regenerate() {
    if (sending || chat.length < 2) return;
    const last = chat[chat.length - 1];
    const asked = chat[chat.length - 2];
    if (last.role !== 'ai' || asked.role !== 'user') return;
    setChat((cur) => cur.slice(0, -2));
    void send(asked.text, true);
  }

  async function send(override?: string, regenerating = false) {
    const message = (override ?? q).trim();

    if (!message || sending) {
      return;
    }

    if (override === undefined) setQ('');
    setErr('');
    const controller = new AbortController();
    abortRef.current = controller;
    setSending(true);
    setLiveStep('');

    try {
      // Tạo hội thoại ở tin nhắn đầu tiên; server đặt tên theo câu hỏi.
      let conversationId = activeId;
      if (!conversationId) {
        const created = await api('/conversations', { method: 'POST' });
        conversationId = created.id as string;
        setActiveId(conversationId);
      }

      setChat((current) => [
        ...current,
        { role: 'user', text: message },
        { role: 'ai', text: '', streaming: true },
      ]);

      const response = await apiFetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          use_rag: useRag,
          conversation_id: conversationId,
          regenerate: regenerating,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(await errorMessageOf(response));
      }

      let finished = false;

      await readSse(response.body, (event, data) => {
        if (event === 'step') {
          setLiveStep((data as LiveStep).step);
        } else if (event === 'reset') {
          // Phần chữ vừa hiện chỉ là lời dẫn trước khi gọi công cụ.
          patchLast((m) => ({ ...m, text: '' }));
        } else if (event === 'delta') {
          patchLast((m) => ({ ...m, text: m.text + data.delta }));
        } else if (event === 'done') {
          finished = true;
          patchLast(() => ({ role: 'ai', text: data.answer, meta: data, id: data.message_id, feedback: null }));
        } else if (event === 'error') {
          throw new Error(data.detail || 'Stream error');
        }
      });

      if (!finished) {
        throw new Error('Kết nối bị ngắt trước khi nhận đủ câu trả lời.');
      }

      await Promise.all([refresh(), loadConversations(), refreshUser()]);
    } catch (error: any) {
      const aborted = error?.name === 'AbortError';
      setChat((current) => {
        const last = current[current.length - 1];
        if (!last?.streaming) return current;
        // Dừng: giữ phần chữ đã nhận (đánh dấu đã dừng); không có chữ nào thì bỏ bong bóng.
        if (aborted && last.text) return [...current.slice(0, -1), { role: 'ai', text: last.text, stopped: true }];
        return current.slice(0, -1);
      });
      if (!aborted) setErr('Chat request failed: ' + error.message);
      loadConversations();
      refreshUser();
    } finally {
      abortRef.current = null;
      setSending(false);
      setLiveStep('');
    }
  }

  return {
    q, setQ, chat, useRag, setUseRag, sending, conversations, activeId, liveStep, messagesRef,
    openConversation, newConversation, removeConversation, renameConversation, send, stop, regenerate, rate,
  };
}
