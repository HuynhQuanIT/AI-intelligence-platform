import logging
import os
import re
import time
import uuid
import asyncio
import json
from contextlib import asynccontextmanager

from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .db import init_pool, query, transaction
from . import conversations
from .graph import graph
from .security import scan_text
from . import embeddings
from .extract import ALLOWED_EXTENSIONS, ExtractError, extension, extract_text
from .rag import (
    DocumentTooLarge,
    DuplicateDocument,
    NoOriginalFile,
    add_document,
    add_uploaded_document,
    delete_document,
    documents,
    get_document,
    get_document_file,
    reindex_missing,
)
from google.genai.errors import ServerError


# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# Application lifecycle
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database resources when the application starts."""
    init_pool()
    try:
        conversations.ensure_schema()
    except Exception:
        logger.exception("Could not create conversation tables")
    yield


app = FastAPI(
    title="AI Intelligence Platform - AI Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# Request models
# =========================================================

class Doc(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    content: str = Field(min_length=1, max_length=200000)


class Eval(BaseModel):
    question: str
    answer: str
    expected: str = ""

class HistoryItem(BaseModel):
    role: str          # "user" hoặc "ai"
    text: str = Field(max_length=12000)


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    use_rag: bool = True
    model: str | None = None
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)
    # Có conversation_id thì server lưu tin nhắn và lấy lịch sử từ database (bỏ qua history do client gửi).
    conversation_id: str | None = None

# =========================================================
# Health check
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "ai-service",
    }

def estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    if provider == "gemini":
        input_rate = float(os.getenv("GEMINI_INPUT_USD_PER_1M_TOKENS", "0"))
        output_rate = float(os.getenv("GEMINI_OUTPUT_USD_PER_1M_TOKENS", "0"))
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    # Công thức demo cho mock/OpenAI
    return input_tokens * 0.00000015 + output_tokens * 0.0000006


def save_request_log(request_id, provider, model, input_tokens,
                     output_tokens, cost, latency_ms, status, trace):
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO usage_logs (request_id, provider, model, input_tokens,
                                    output_tokens, cost_usd, latency_ms, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (request_id, provider, model, input_tokens,
             output_tokens, cost, latency_ms, status),
        )
        for item in trace:
            cur.execute(
                "INSERT INTO traces (request_id, step, status, detail) "
                "VALUES (%s, %s, %s, %s)",
                (request_id, item["step"], item["status"], Jsonb(item["detail"])),
            )


async def safe_log(**kwargs):
    """Ghi log ở thread riêng; lỗi ghi log không được làm hỏng response."""
    try:
        await asyncio.to_thread(save_request_log, **kwargs)
    except Exception:
        logger.exception("Failed to save request log")

def save_security_event(request_id, blocked, matches):
    query(
        """
        INSERT INTO security_events (request_id, severity, event_type, description)
        VALUES (%s, %s, %s, %s)
        """,
        (
            request_id,
            "high" if blocked else "medium",
            "prompt_injection" if blocked else "context_injection",
            ", ".join(matches),
        ),
        False,
    )


async def safe_security_event(request_id, blocked, matches):
    try:
        await asyncio.to_thread(save_security_event, request_id, blocked, matches)
    except Exception:
        logger.exception("Failed to save security event")

# =========================================================
# Chat
# =========================================================

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
    rồi lưu ngay tin nhắn người dùng (không mất nếu model lỗi)."""
    if not b.conversation_id:
        return None, [h.model_dump() for h in b.history[-10:]]

    try:
        cid = conversations.parse_id(b.conversation_id)
        if not await asyncio.to_thread(conversations.exists, cid):
            raise conversations.ConversationNotFound(cid)
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")

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


async def log_failure(request_id, provider, model, latency_ms):
    await safe_log(
        request_id=request_id, provider=provider, model=model or "",
        input_tokens=0, output_tokens=0, cost=0,
        latency_ms=latency_ms, status="error", trace=[],
    )


@app.post("/chat")
async def chat(b: Chat):
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - start_time) * 1000)

    conversation_id, history = await prepare_conversation(b)

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


@app.post("/chat/stream")
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
    conversation_id, history = await prepare_conversation(b)

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


# =========================================================
# Conversations
# =========================================================

@app.post("/conversations")
def create_conversation():
    return conversations.create()


@app.get("/conversations")
def list_conversations():
    return conversations.list_all()


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str):
    try:
        return conversations.messages(conversations.parse_id(conversation_id))
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    try:
        cid = conversations.parse_id(conversation_id)
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversations.delete(cid):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": cid}


# =========================================================
# Documents
# =========================================================

@app.post("/documents")
def create_doc(b: Doc):
    return add_document(
        title=b.title,
        content=b.content,
    )


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=250),
):
    filename = file.filename or ""
    ext = extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Chỉ hỗ trợ: " + ", ".join(sorted(ALLOWED_EXTENSIONS)),
        )

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File vượt quá 10 MB.")
    if not data:
        raise HTTPException(status_code=422, detail="File rỗng.")

    try:
        text = await asyncio.to_thread(extract_text, filename, data)
        result = await asyncio.to_thread(
            add_uploaded_document, filename, title, data, text
        )
    except ExtractError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DocumentTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except DuplicateDocument as exc:
        raise HTTPException(
            status_code=409,
            detail=f"File này đã được index (tài liệu '{exc.title}', id {exc.document_id}).",
        )
    except Exception:
        logger.exception("Document upload failed: %s", filename)
        raise HTTPException(
            status_code=503,
            detail="Không lưu được tài liệu (MinIO hoặc database lỗi). Xem log ai-service.",
        )

    # Không chặn việc lưu: lọc thật sự nằm ở Analysis Agent lúc truy xuất.
    result["security_matches"] = scan_text(text)
    return result


@app.get("/documents")
def get_docs():
    return documents()

def valid_document_id(value: str) -> str:
    """id không phải UUID thì coi như không tồn tại (tránh lỗi 500 từ cột uuid)."""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")


@app.get("/documents/{document_id}")
def get_doc_detail(document_id: str):
    document = get_document(valid_document_id(document_id))

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    return document

@app.delete("/documents/{document_id}")
def delete_doc(document_id: str):
    document_id = valid_document_id(document_id)
    if not delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}


@app.get("/documents/{document_id}/file")
def download_doc(document_id: str):
    document_id = valid_document_id(document_id)
    try:
        found = get_document_file(document_id)
    except NoOriginalFile:
        raise HTTPException(
            status_code=404,
            detail="Tài liệu này được dán trực tiếp, không có file gốc.",
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="File gốc không còn trong kho lưu trữ."
        )

    if found is None:
        raise HTTPException(status_code=404, detail="Document not found")

    filename, content_type, data = found
    encoded = quote(filename)
    ascii_name = filename.encode("ascii", "ignore").decode() or "document"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            # File do người dùng tải lên là dữ liệu không tin cậy: luôn tải về, không mở trực tiếp.
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}",
            "X-Content-Type-Options": "nosniff",
            "X-Document-Filename": encoded,
        },
    )


@app.post("/documents/reindex")
def reindex_documents():
    if not embeddings.enabled():
        raise HTTPException(
            status_code=400,
            detail="Embeddings are disabled: need LLM_PROVIDER=gemini and GEMINI_API_KEY.",
        )
    return reindex_missing()
    
# =========================================================
# Agents
# =========================================================

@app.get("/agents")
def agents():
    return query(
        """
        SELECT
            id,
            name,
            description,
            role,
            enabled
        FROM agents
        ORDER BY id
        """
    )


# =========================================================
# Metrics
# =========================================================

@app.get("/metrics")
def metrics():
    totals = query(
        """
        SELECT
            COUNT(*)::int AS requests,
            COALESCE(SUM(cost_usd), 0)::float AS cost_usd,
            COALESCE(AVG(latency_ms), 0)::int AS avg_latency_ms,
            COALESCE(
                SUM(input_tokens + output_tokens),
                0
            )::int AS total_tokens
        FROM usage_logs
        """
    )[0]

    recent = query(
        """
        SELECT
            request_id,
            model,
            input_tokens,
            output_tokens,
            cost_usd::float,
            latency_ms,
            status,
            created_at
        FROM usage_logs
        ORDER BY id DESC
        LIMIT 20
        """
    )

    return {
        "totals": totals,
        "recent": recent,
    }


# =========================================================
# Traces
# =========================================================

@app.get("/traces")
def traces():
    return query(
        """
        SELECT
            id,
            request_id,
            step,
            status,
            detail,
            created_at
        FROM traces
        ORDER BY id DESC
        LIMIT 100
        """
    )


# =========================================================
# Evaluation
# =========================================================

@app.post("/evaluate")
def evaluate(b: Eval):
    expected_terms = set(
        re.findall(r"\w+", b.expected.lower())
    )

    answer_terms = set(
        re.findall(r"\w+", b.answer.lower())
    )

    matched_terms = expected_terms & answer_terms

    score = len(matched_terms) / max(
        1,
        len(expected_terms),
    )

    return {
        "faithfulness_proxy": round(score, 3),
        "matched_terms": len(matched_terms),
        "reference_terms": len(expected_terms),
        "note": (
            "Heuristic demo metric, "
            "not validated factual accuracy."
        ),
    }


# =========================================================
# Security scan
# =========================================================

@app.post("/security/scan")
def scan(b: dict):
    matches = scan_text(str(b.get("text", "")))

    if matches:
        query(
            """
            INSERT INTO security_events (
                request_id,
                severity,
                event_type,
                description
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                "high",
                "prompt_injection",
                ", ".join(matches),
            ),
            False,
        )

    return {
        "safe": not bool(matches),
        "severity": "high" if matches else "low",
        "matches": matches,
    }


@app.get("/security/events")
def events():
    return query(
        """
        SELECT
            id,
            request_id,
            severity,
            event_type,
            description,
            created_at
        FROM security_events
        ORDER BY id DESC
        LIMIT 100
        """
    )