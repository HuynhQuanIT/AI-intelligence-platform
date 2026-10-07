"""Nghiệp vụ chat dùng chung cho /chat và /chat/stream."""
import asyncio
import logging

from ..schemas import Chat
from . import conversations
from .telemetry import estimate_cost, safe_log, safe_security_event

logger = logging.getLogger(__name__)


def initial_state(b: Chat, history: list, stream: bool = False) -> dict:
    return {
        "message": b.message,
        "use_rag": b.use_rag,
        "model": b.model,
        "context": [],
        "answer": "",
        "trace": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "selected_model": "",
        "history": history,
        "route": "",
        "enabled": [],
        "blocked": False,
        "security_matches": [],
        "stream": stream,
    }


async def prepare_conversation(b: Chat):
    """Trả (conversation_id | None, history). Có conversation_id thì lấy lịch sử từ DB
    rồi lưu ngay tin nhắn người dùng (không mất nếu model lỗi).
    Ném conversations.ConversationNotFound nếu cuộc trò chuyện không tồn tại."""
    if not b.conversation_id:
        return None, [h.model_dump() for h in b.history[-10:]]

    cid = conversations.parse_id(b.conversation_id)
    if not await asyncio.to_thread(conversations.exists, cid):
        raise conversations.ConversationNotFound(cid)

    history = await asyncio.to_thread(conversations.recent_history, cid)
    await asyncio.to_thread(conversations.add_message, cid, "user", b.message)
    return cid, history


def source_summary(sources: list) -> list:
    """Chỉ lưu thông tin nguồn (không lưu nội dung chunk) để bảng messages gọn."""
    return [
        {
            "title": x.get("title"),
            "document_id": x.get("document_id"),
            "chunk_index": x.get("chunk_index"),
            "similarity": x.get("similarity"),
        }
        for x in sources
    ]


async def finish_chat(request_id, provider, state, latency_ms, conversation_id):
    """Dùng chung cho /chat và /chat/stream: ghi log, sự kiện bảo mật, lưu tin nhắn, dựng payload."""
    cost = estimate_cost(provider, state["input_tokens"], state["output_tokens"])
    status = "blocked" if state["blocked"] else "success"

    await safe_log(
        request_id=request_id, provider=provider,
        model=state["selected_model"],
        input_tokens=state["input_tokens"],
        output_tokens=state["output_tokens"],
        cost=cost, latency_ms=latency_ms, status=status,
        trace=state["trace"],
    )

    if state["security_matches"]:
        await safe_security_event(
            request_id, state["blocked"], state["security_matches"]
        )

    payload = {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "answer": state["answer"],
        "model": state["selected_model"],
        "input_tokens": state["input_tokens"],
        "output_tokens": state["output_tokens"],
        "cost_usd": round(cost, 6),
        "latency_ms": latency_ms,
        "blocked": state["blocked"],
        "sources": state["context"],
        "trace": state["trace"],
    }

    if conversation_id:
        meta = {
            "model": payload["model"],
            "input_tokens": payload["input_tokens"],
            "output_tokens": payload["output_tokens"],
            "cost_usd": payload["cost_usd"],
            "latency_ms": latency_ms,
            "blocked": payload["blocked"],
            "sources": source_summary(state["context"]),
            "trace": state["trace"],
        }
        try:
            await asyncio.to_thread(
                conversations.add_message, conversation_id, "ai", state["answer"], meta
            )
        except Exception:
            logger.exception("Failed to save assistant message")

    return payload
