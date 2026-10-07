import { useEffect, useRef, useState } from 'react';
import { API, api } from '../api/client';
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
  const messagesRef = useRef<HTMLDivElement | null>(null);

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
      setChat(rows.map((m: any) => ({ role: m.role, text: m.text, meta: m.meta })));
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

  async function send() {
    const message = q.trim();

    if (!message || sending) {
      return;
    }

    setQ('');
    setErr('');
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

      const response = await fetch(API + '/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          use_rag: useRag,
          conversation_id: conversationId,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(await response.text());
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
          patchLast(() => ({ role: 'ai', text: data.answer, meta: data }));
        } else if (event === 'error') {
          throw new Error(data.detail || 'Stream error');
        }
      });

      if (!finished) {
        throw new Error('Kết nối bị ngắt trước khi nhận đủ câu trả lời.');
      }

      await Promise.all([refresh(), loadConversations()]);
    } catch (error: any) {
      // Bỏ bong bóng AI đang dở; tin nhắn người dùng vẫn được lưu trong hội thoại.
      setChat((current) =>
        current.length && current[current.length - 1].streaming
          ? current.slice(0, -1)
          : current
      );
      setErr('Chat request failed: ' + error.message);
      loadConversations();
    } finally {
      setSending(false);
      setLiveStep('');
    }
  }

  return {
    q, setQ, chat, useRag, setUseRag, sending, conversations, activeId, liveStep, messagesRef,
    openConversation, newConversation, removeConversation, send,
  };
}
