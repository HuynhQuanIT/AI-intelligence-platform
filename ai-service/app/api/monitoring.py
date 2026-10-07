"""Giám sát: danh sách agent, số liệu sử dụng, trace và đánh giá nhanh."""
import re

from fastapi import APIRouter

from ..core.db import query
from ..schemas import Eval

router = APIRouter(tags=["monitoring"])


@router.get("/agents")
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


@router.get("/metrics")
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


@router.get("/traces")
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


@router.post("/evaluate")
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
