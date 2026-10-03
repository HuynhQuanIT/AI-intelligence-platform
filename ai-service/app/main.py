import logging
import os
import re
import time
import uuid
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .db import init_pool, query, transaction
from .graph import graph
from .security import scan_text
from . import embeddings
from .rag import add_document, documents, get_document, reindex_missing
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

@app.post("/chat")
async def chat(b: Chat):
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - start_time) * 1000)

    try:
        state = await graph.ainvoke(
            {
                "message": b.message,
                "use_rag": b.use_rag,
                "model": b.model,
                "context": [],
                "answer": "",
                "trace": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "selected_model": "",
                "history": [h.model_dump() for h in b.history[-10:]],
                "route": "",
                "enabled": [],
                "blocked": False,
                "security_matches": [],
            }
        )
    except ServerError as exc:
        logger.exception("Gemini service error. Request ID: %s", request_id)
        await safe_log(
            request_id=request_id, provider=provider, model=b.model or "",
            input_tokens=0, output_tokens=0, cost=0,
            latency_ms=elapsed_ms(), status="error", trace=[],
        )
        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily unavailable. Please try again later.",
            headers={"Retry-After": "10"},
        ) from exc
    except Exception:
        logger.exception("AI chat request failed. Request ID: %s", request_id)
        await safe_log(
            request_id=request_id, provider=provider, model=b.model or "",
            input_tokens=0, output_tokens=0, cost=0,
            latency_ms=elapsed_ms(), status="error", trace=[],
        )
        raise HTTPException(
            status_code=500,
            detail="AI request failed. Check ai-service logs for details.",
        )

    latency_ms = elapsed_ms()
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

    return {
        "request_id": request_id,
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

# =========================================================
# Documents
# =========================================================

@app.post("/documents")
def create_doc(b: Doc):
    return add_document(
        title=b.title,
        content=b.content,
    )


@app.get("/documents")
def get_docs():
    return documents()

@app.get("/documents/{document_id}")
def get_doc_detail(document_id: str):
    document = get_document(document_id)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    return document

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