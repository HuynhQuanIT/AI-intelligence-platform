"""POST /chat và POST /chat/stream (SSE)."""
import json
import logging
import os
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from google.genai.errors import ServerError

from ..agents.graph import graph
from ..services import conversations
from ..services.chat import finish_chat, initial_state, prepare_conversation
from ..services.telemetry import log_failure
from ..schemas import Chat

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


async def prepare(b: Chat):
    try:
        return await prepare_conversation(b)
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.post("/chat")
async def chat(b: Chat):
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - start_time) * 1000)

    conversation_id, history = await prepare(b)

    try:
        state = await graph.ainvoke(initial_state(b, history))
    except ServerError as exc:
        logger.exception("Gemini service error. Request ID: %s", request_id)
        await log_failure(request_id, provider, b.model, elapsed_ms())
        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily unavailable. Please try again later.",
            headers={"Retry-After": "10"},
        ) from exc
    except Exception:
        logger.exception("AI chat request failed. Request ID: %s", request_id)
        await log_failure(request_id, provider, b.model, elapsed_ms())
        raise HTTPException(
            status_code=500,
            detail="AI request failed. Check ai-service logs for details.",
        )

    return await finish_chat(request_id, provider, state, elapsed_ms(), conversation_id)


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
async def chat_stream(b: Chat):
    """
    Server-Sent Events. Các sự kiện:
      start  {request_id, conversation_id}
      step   {step, status, detail}      mỗi agent xong một bước
      delta  {delta}                      một đoạn câu trả lời
      done   {...như /chat}               kết quả cuối (answer đầy đủ, token, chi phí, nguồn, trace)
      error  {detail}
    """
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    # Lỗi 404 phải trả trước khi mở luồng để client nhận đúng mã HTTP.
    conversation_id, history = await prepare(b)

    def elapsed_ms() -> int:
        return int((time.perf_counter() - start_time) * 1000)

    async def events():
        yield sse("start", {"request_id": request_id, "conversation_id": conversation_id})

        state = initial_state(b, history, stream=True)
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
                request_id, provider, state, elapsed_ms(), conversation_id
            )
            yield sse("done", payload)

        except ServerError:
            logger.exception("Gemini service error. Request ID: %s", request_id)
            await log_failure(request_id, provider, b.model, elapsed_ms())
            yield sse("error", {"detail": "Gemini is temporarily unavailable. Please try again later."})
        except Exception:
            logger.exception("AI stream failed. Request ID: %s", request_id)
            await log_failure(request_id, provider, b.model, elapsed_ms())
            yield sse("error", {"detail": "AI request failed. Check ai-service logs for details."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
