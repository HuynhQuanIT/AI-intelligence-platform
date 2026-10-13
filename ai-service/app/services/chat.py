"""Nghiệp vụ chat dùng chung cho /chat và /chat/stream."""
import asyncio
import logging
import uuid

from ..rag.access import PUBLIC_ONLY
from ..schemas import Chat
from . import conversations, groups
from .telemetry import estimate_cost, safe_log, safe_security_event

logger = logging.getLogger(__name__)


MAX_ATTACHMENT_CHARS = 24000  # phần nội dung file đưa thẳng vào prompt; file dài hơn thì model dùng công cụ đọc tiếp


class AttachmentError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def load_attachment(attachment_id: str | None, viewer: dict) -> dict | None:
    """Nội dung file đính kèm cho lượt chat này. Chỉ nhận tài liệu người xem được phép xem và đã xử lý xong;
    id lạ/không có quyền đều báo như nhau (không lộ sự tồn tại của tài liệu người khác)."""
    if not attachment_id:
        return None
    from ..rag.documents import attachment_chunks, get_document
    try:
        did = str(uuid.UUID(attachment_id))
    except ValueError:
        raise AttachmentError(404, "Không tìm thấy file đính kèm.")
    doc = get_document(did, viewer)
    if doc is None:
        raise AttachmentError(404, "Không tìm thấy file đính kèm.")
    if doc["status"] != "processed":
        raise AttachmentError(409, "File đính kèm chưa xử lý xong hoặc bị lỗi.")
    chunks, total = attachment_chunks(did, MAX_ATTACHMENT_CHARS)
    return {"document_id": did, "title": doc["title"], "filename": doc["filename"],
            "chunks": chunks, "total_chunks": total}


def initial_state(b: Chat, history: list, stream: bool = False, viewer: dict | None = None,
                  attachment: dict | None = None) -> dict:
    return {
        "attachment": attachment,
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
        # Người xem quyết định tài liệu nào được truy xuất; mặc định chỉ thấy tài liệu công khai.
        "viewer": viewer or PUBLIC_ONLY,
    }


async def prepare_conversation(b: Chat, user_id: str, attachment: dict | None = None):
    """Trả (conversation_id | None, history). Có conversation_id thì lấy lịch sử từ DB
    rồi lưu ngay tin nhắn người dùng (không mất nếu model lỗi).
    Ném conversations.ConversationNotFound nếu hội thoại không tồn tại hoặc không phải của user_id."""
    if not b.conversation_id:
        return None, [h.model_dump() for h in b.history[-10:]]

    cid = conversations.parse_id(b.conversation_id)
    if not await asyncio.to_thread(conversations.exists, cid, user_id):
        raise conversations.ConversationNotFound(cid)

    if b.regenerate:
        await asyncio.to_thread(conversations.drop_last_exchange, cid, b.message)
    history = await asyncio.to_thread(conversations.recent_history, cid)
    meta = {"attachment": {"document_id": attachment["document_id"], "title": attachment["title"],
                           "filename": attachment["filename"]}} if attachment else None
    await asyncio.to_thread(conversations.add_message, cid, "user", b.message, meta)
    return cid, history


def source_summary(sources: list) -> list:
    """Chỉ lưu thông tin nguồn (không lưu nội dung chunk) để bảng messages gọn."""
    return [
        {
            "title": x.get("title"),
            "document_id": x.get("document_id"),
            "chunk_index": x.get("chunk_index"),
            "similarity": x.get("similarity"),
            "snippet": (x.get("content") or "")[:200],
            "scope": x.get("scope"),
            "groups": x.get("groups", []),
        }
        for x in sources
    ]


async def finish_chat(request_id, provider, state, latency_ms, conversation_id, user_id=None):
    """Dùng chung cho /chat và /chat/stream: ghi log, sự kiện bảo mật, lưu tin nhắn, dựng payload."""
    cost = estimate_cost(provider, state["input_tokens"], state["output_tokens"])
    status = "blocked" if state["blocked"] else "success"

    await safe_log(
        request_id=request_id, provider=provider,
        model=state["selected_model"],
        input_tokens=state["input_tokens"],
        output_tokens=state["output_tokens"],
        cost=cost, latency_ms=latency_ms, status=status,
        trace=state["trace"], user_id=user_id,
    )

    if state["security_matches"]:
        await safe_security_event(
            request_id, state["blocked"], state["security_matches"], user_id
        )

    try:  # nhãn nhóm chỉ để hiển thị: lỗi ở đây không được làm hỏng câu trả lời
        sources = await asyncio.to_thread(groups.label_sources, state.get("viewer"), state["context"])
    except Exception:
        logger.exception("Không gắn được nhãn nhóm cho nguồn trích dẫn")
        sources = state["context"]

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
        "sources": sources,
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
            "sources": source_summary(sources),
            "trace": state["trace"],
        }
        try:
            payload["message_id"] = await asyncio.to_thread(
                conversations.add_message, conversation_id, "ai", state["answer"], meta
            )
        except Exception:
            logger.exception("Failed to save assistant message")

    return payload
