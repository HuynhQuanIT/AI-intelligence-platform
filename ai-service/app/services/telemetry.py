"""Ghi nhận vận hành: chi phí, nhật ký request, trace và sự kiện bảo mật."""
import asyncio
import logging
import os

from psycopg.types.json import Jsonb

from ..core.db import query, transaction

logger = logging.getLogger(__name__)


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


async def log_failure(request_id, provider, model, latency_ms):
    await safe_log(
        request_id=request_id, provider=provider, model=model or "",
        input_tokens=0, output_tokens=0, cost=0,
        latency_ms=latency_ms, status="error", trace=[],
    )
