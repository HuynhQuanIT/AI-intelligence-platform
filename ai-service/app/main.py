import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .db import init_pool, query
from .graph import graph
from .rag import add_document, documents, get_document
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

class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    use_rag: bool = True
    model: str | None = None


class Doc(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    content: str = Field(min_length=1, max_length=200000)


class Eval(BaseModel):
    question: str
    answer: str
    expected: str = ""


# =========================================================
# Health check
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "ai-service",
    }


# =========================================================
# Chat
# =========================================================

@app.post("/chat")
async def chat(b: Chat):
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())

    try:
        # Execute the LangGraph workflow.
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
            }
        )

        latency_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        # Determine the configured LLM provider.
        provider = os.getenv(
            "LLM_PROVIDER",
            "mock",
        ).strip().lower()

        # Calculate estimated request cost.
        if provider == "gemini":
            input_rate = float(
                os.getenv(
                    "GEMINI_INPUT_USD_PER_1M_TOKENS",
                    "0",
                )
            )

            output_rate = float(
                os.getenv(
                    "GEMINI_OUTPUT_USD_PER_1M_TOKENS",
                    "0",
                )
            )

            cost = (
                state["input_tokens"] * input_rate
                + state["output_tokens"] * output_rate
            ) / 1_000_000

        else:
            # Legacy demo formula for mock/OpenAI.
            cost = (
                state["input_tokens"] * 0.00000015
                + state["output_tokens"] * 0.0000006
            )

        # Save usage metrics.
        query(
            """
            INSERT INTO usage_logs (
                request_id,
                provider,
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                latency_ms
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request_id,
                provider,
                state["selected_model"],
                state["input_tokens"],
                state["output_tokens"],
                cost,
                latency_ms,
            ),
            False,
        )

        # Save execution traces.
        for trace_item in state["trace"]:
            query(
                """
                INSERT INTO traces (
                    request_id,
                    step,
                    status,
                    detail
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    request_id,
                    trace_item["step"],
                    trace_item["status"],
                    Jsonb(trace_item["detail"]),
                ),
                False,
            )

        return {
            "request_id": request_id,
            "answer": state["answer"],
            "model": state["selected_model"],
            "input_tokens": state["input_tokens"],
            "output_tokens": state["output_tokens"],
            "cost_usd": round(cost, 6),
            "latency_ms": latency_ms,
            "sources": state["context"],
            "trace": state["trace"],
        }

    except ServerError as exc:
        logger.exception(
            "Gemini service error. Request ID: %s",
            request_id,
        )

        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily unavailable. Please try again later.",
            headers={"Retry-After": "10"},
        ) from exc

    except Exception:
        logger.exception(
            "AI chat request failed. Request ID: %s",
            request_id,
        )

        raise HTTPException(
            status_code=500,
            detail="AI request failed. Check ai-service logs for details.",
        )


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
    text = str(
        b.get("text", "")
    ).lower()

    patterns = [
        "ignore previous instructions",
        "reveal system prompt",
        "print api key",
        "bypass security",
    ]

    matches = [
        pattern
        for pattern in patterns
        if pattern in text
    ]

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