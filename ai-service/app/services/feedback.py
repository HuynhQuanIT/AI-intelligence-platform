"""Đánh giá 👍/👎 cho từng câu trả lời của chatbot, để gom dữ liệu cải thiện chất lượng.

Mỗi người chỉ đánh giá được câu trả lời trong hội thoại của chính mình (một đánh giá / câu, đổi được).
Admin xem tổng hợp và các câu bị 👎 gần đây (kèm câu hỏi, câu trả lời, nguồn) để biết chatbot sai ở đâu.
"""
from ..core.db import query, transaction

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS message_feedback(
        message_id BIGINT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rating SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
        comment TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS message_feedback_rating_idx ON message_feedback(rating, updated_at DESC)",
]


class MessageNotFound(Exception):
    pass


def ensure_schema() -> None:
    with transaction() as cur:
        for statement in SCHEMA:
            cur.execute(statement)


def set_feedback(message_id: int, user_id: str, rating: int, comment: str | None = None) -> dict:
    """rating 1/-1 ghi (hoặc đổi) đánh giá, 0 xóa đánh giá. Chỉ áp dụng cho câu trả lời (role='ai')
    thuộc hội thoại của user_id; ngược lại coi như không tồn tại."""
    owned = query(
        "SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.id = %s AND m.role = 'ai' AND c.user_id = %s",
        (message_id, user_id),
    )
    if not owned:
        raise MessageNotFound(message_id)
    comment = (comment or "").strip() or None
    with transaction() as cur:
        if rating == 0:
            cur.execute("DELETE FROM message_feedback WHERE message_id = %s AND user_id = %s",
                        (message_id, user_id))
        else:
            cur.execute(
                "INSERT INTO message_feedback(message_id, user_id, rating, comment) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (message_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, "
                "updated_at = NOW()",
                (message_id, user_id, rating, comment),
            )
    return {"message_id": message_id, "rating": rating or None, "comment": comment if rating else None}


def summary(recent: int = 30) -> dict:
    totals = query(
        "SELECT COUNT(*) FILTER (WHERE rating = 1) AS up, COUNT(*) FILTER (WHERE rating = -1) AS down "
        "FROM message_feedback"
    )[0]
    answers = query("SELECT COUNT(*) AS n FROM messages WHERE role = 'ai'")[0]["n"]
    up, down = int(totals["up"]), int(totals["down"])
    rated = up + down
    rows = query(
        """
        SELECT f.message_id, f.comment, f.updated_at, u.email, m.content AS answer, m.meta,
               (SELECT q.content FROM messages q WHERE q.conversation_id = m.conversation_id
                  AND q.role = 'user' AND q.id < m.id ORDER BY q.id DESC LIMIT 1) AS question
        FROM message_feedback f
        JOIN messages m ON m.id = f.message_id
        JOIN users u ON u.id = f.user_id
        WHERE f.rating = -1
        ORDER BY f.updated_at DESC LIMIT %s
        """,
        (recent,),
    )
    return {
        "up": up,
        "down": down,
        "rated": rated,
        "answers": int(answers),
        "satisfaction": round(up / rated, 3) if rated else None,
        "rating_rate": round(rated / answers, 3) if answers else None,
        "recent_down": [
            {
                "message_id": r["message_id"],
                "question": r["question"],
                "answer": (r["answer"] or "")[:500],
                "comment": r["comment"],
                "user": r["email"],
                "sources": [s.get("title") for s in (r["meta"] or {}).get("sources", [])],
                "at": r["updated_at"].isoformat(),
            }
            for r in rows
        ],
    }
