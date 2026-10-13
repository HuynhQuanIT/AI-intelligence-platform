"""POST /chat và POST /chat/stream (SSE)."""
import asyncio
import json
import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from google.genai.errors import ServerError

from ..agents.graph import graph
from ..rag.access import viewer_of
from ..core import settings
from ..services import auth, conversations, ratelimit
from ..services.chat import AttachmentError, finish_chat, initial_state, load_attachment, prepare_conversation
from ..services.telemetry import log_failure
from ..core.db import query
from ..rag.documents import DuplicateDocument, delete_document, process_document, start_upload, user_document_count
from ..rag.extract import ALLOWED_EXTENSIONS, extension
from ..schemas import Chat
from .deps import current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def check_rate_limit(user: dict) -> None:
    """Giới hạn số tin nhắn mỗi phút của từng người (trong bộ nhớ)."""
    wait = ratelimit.hit(f"chat:{user['id']}", settings.chat_rate_per_minute(), 60)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Bạn gửi quá nhanh. Hãy thử lại sau {wait} giây.",
            headers={"Retry-After": str(wait)},
        )


def check_quota(user: dict) -> None:
    """Hạn mức tin nhắn mỗi ngày (khác giới hạn tốc độ mỗi phút)."""
    try:
        auth.check_quota(user)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message,
                            headers={"Retry-After": str(exc.retry_after or 60)})


async def prepare(b: Chat, user: dict):
    """Trả (conversation_id, history, attachment). Lỗi 404/409 được trả trước khi gọi model hay mở luồng."""
    try:
        attachment = await asyncio.to_thread(load_attachment, b.attachment_id, viewer_of(user))
    except AttachmentError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    try:
        cid, history = await prepare_conversation(b, user["id"], attachment)
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return cid, history, attachment


@router.post("/chat")
async def chat(b: Chat, user: dict = Depends(current_user)):
    check_rate_limit(user)
    check_quota(user)
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - start_time) * 1000)

    conversation_id, history, attachment = await prepare(b, user)

    try:
        state = await graph.ainvoke(initial_state(b, history, viewer=viewer_of(user), attachment=attachment))
    except ServerError as exc:
        logger.exception("Gemini service error. Request ID: %s", request_id)
        await log_failure(request_id, provider, b.model, elapsed_ms(), user["id"])
        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily unavailable. Please try again later.",
            headers={"Retry-After": "10"},
        ) from exc
    except Exception:
        logger.exception("AI chat request failed. Request ID: %s", request_id)
        await log_failure(request_id, provider, b.model, elapsed_ms(), user["id"])
        raise HTTPException(
            status_code=500,
            detail="AI request failed. Check ai-service logs for details.",
        )

    return await finish_chat(request_id, provider, state, elapsed_ms(), conversation_id, user["id"])


MAX_ATTACH_BYTES = 10 * 1024 * 1024
MAX_USER_DOCUMENTS = int(os.getenv("MAX_USER_DOCUMENTS", "200"))
ATTACH_TIMEOUT_SECONDS = int(os.getenv("ATTACH_TIMEOUT_SECONDS", "75"))


@router.post("/chat/attachments", status_code=201)
async def upload_attachment(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Đính kèm file vào khung chat: lưu thành tài liệu RIÊNG TƯ của người dùng (hiện ở Knowledge Center của họ),
    đọc xong mới trả kết quả để lượt chat kế tiếp phân tích được ngay. File lỗi không để lại rác."""
    uid = str(user["id"])
    wait = ratelimit.hit(f"attach:{uid}", 10, 60)
    if wait:
        raise HTTPException(status_code=429, detail=f"Bạn tải file quá nhanh. Thử lại sau {wait} giây.",
                            headers={"Retry-After": str(wait)})
    filename = file.filename or ""
    if extension(filename) not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Chỉ hỗ trợ: " + ", ".join(sorted(ALLOWED_EXTENSIONS)))
    data = await file.read(MAX_ATTACH_BYTES + 1)
    if len(data) > MAX_ATTACH_BYTES:
        raise HTTPException(status_code=413, detail="File vượt quá 10 MB.")
    if not data:
        raise HTTPException(status_code=422, detail="File rỗng.")
    if await asyncio.to_thread(user_document_count, uid) >= MAX_USER_DOCUMENTS:
        raise HTTPException(status_code=409, detail="Bạn đã đạt giới hạn số file riêng. Hãy xóa bớt trong Knowledge Center.")

    reused = False
    try:
        info = await asyncio.to_thread(start_upload, filename, None, data, uid)
    except DuplicateDocument as exc:
        # Đã tải đúng file này trước đó: dùng lại nếu còn dùng được, còn không thì xóa bản lỗi để tải lại.
        row = (await asyncio.to_thread(query, "SELECT status FROM documents WHERE id = %s", (exc.document_id,)))[0]
        if row["status"] == "processed":
            info, reused = {"id": exc.document_id, "title": exc.title, "filename": filename}, True
        else:
            await asyncio.to_thread(delete_document, exc.document_id)
            info = await asyncio.to_thread(start_upload, filename, None, data, uid)
    except Exception:
        logger.exception("Chat attachment upload failed: %s", filename)
        raise HTTPException(status_code=503, detail="Không lưu được file (kho lưu trữ hoặc database lỗi).")

    if not reused:
        try:
            await asyncio.wait_for(asyncio.to_thread(process_document, info["id"]), ATTACH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="File lớn nên chưa đọc xong. Hãy xem trạng thái trong Knowledge Center.")

    row = (await asyncio.to_thread(
        query,
        "SELECT status, error, title, filename, size_bytes, "
        "(SELECT COUNT(*)::int FROM document_chunks WHERE document_id = d.id) AS chunks "
        "FROM documents d WHERE id = %s", (info["id"],)))[0]
    if row["status"] != "processed":
        await asyncio.to_thread(delete_document, info["id"])
        raise HTTPException(status_code=422, detail=row["error"] or "Không đọc được file này.")
    return {"id": info["id"], "title": row["title"], "filename": row["filename"], "size_bytes": row["size_bytes"],
            "chunks": row["chunks"], "status": "processed", "reused": reused}


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
async def chat_stream(b: Chat, user: dict = Depends(current_user)):
    """
    Server-Sent Events. Các sự kiện:
      start  {request_id, conversation_id}
      step   {step, status, detail}      mỗi agent xong một bước
      delta  {delta}                      một đoạn câu trả lời
      done   {...như /chat}               kết quả cuối (answer đầy đủ, token, chi phí, nguồn, trace)
      error  {detail}
    """
    check_rate_limit(user)
    check_quota(user)
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    # Lỗi 404 phải trả trước khi mở luồng để client nhận đúng mã HTTP.
    conversation_id, history, attachment = await prepare(b, user)

    def elapsed_ms() -> int:
        return int((time.perf_counter() - start_time) * 1000)

    async def events():
        yield sse("start", {"request_id": request_id, "conversation_id": conversation_id})

        state = initial_state(b, history, stream=True, viewer=viewer_of(user), attachment=attachment)
        emitted = 0
        streamed = False

        try:
            async for mode, chunk in graph.astream(state, stream_mode=["updates", "custom"]):
                if mode == "custom":
                    if chunk.get("reset"):
                        # Lượt model vừa rồi chỉ là lời dẫn trước khi gọi công cụ: bên nhận xóa đi.
                        yield sse("reset", {})
                        streamed = False
                    else:
                        streamed = True
                        yield sse("delta", chunk)
                    continue

                for update in chunk.values():
                    if not update:
                        continue
                    state.update(update)
                    for item in state["trace"][emitted:]:
                        yield sse("step", item)
                    emitted = len(state["trace"])

            # Bị chặn hoặc agent có công cụ: câu trả lời có sẵn nguyên khối, gửi một lần.
            if not streamed and state["answer"]:
                yield sse("delta", {"delta": state["answer"]})

            payload = await finish_chat(
                request_id, provider, state, elapsed_ms(), conversation_id, user["id"]
            )
            yield sse("done", payload)

        except ServerError:
            logger.exception("Gemini service error. Request ID: %s", request_id)
            await log_failure(request_id, provider, b.model, elapsed_ms(), user["id"])
            yield sse("error", {"detail": "Gemini is temporarily unavailable. Please try again later."})
        except Exception:
            logger.exception("AI stream failed. Request ID: %s", request_id)
            await log_failure(request_id, provider, b.model, elapsed_ms(), user["id"])
            yield sse("error", {"detail": "AI request failed. Check ai-service logs for details."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
