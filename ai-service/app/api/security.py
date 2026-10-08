"""Security Center: quét văn bản và xem sự kiện bảo mật."""
import uuid

from fastapi import APIRouter, Depends

from ..agents.security import scan_text
from ..core.db import query
from .deps import require_admin

router = APIRouter(tags=["security"], dependencies=[Depends(require_admin)])


@router.post("/security/scan")
def scan(b: dict, admin: dict = Depends(require_admin)):
    matches = scan_text(str(b.get("text", "")))

    if matches:
        query(
            """
            INSERT INTO security_events (
                request_id,
                severity,
                event_type,
                description,
                user_id
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                "high",
                "prompt_injection",
                ", ".join(matches),
                admin["id"],
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
