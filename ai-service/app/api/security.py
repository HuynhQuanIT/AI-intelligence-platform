"""Security Center: quét văn bản và xem sự kiện bảo mật."""
import uuid

from fastapi import APIRouter

from ..agents.security import scan_text
from ..core.db import query

router = APIRouter(tags=["security"])


@router.post("/security/scan")
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


@router.get("/security/events")
def security_events():
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
