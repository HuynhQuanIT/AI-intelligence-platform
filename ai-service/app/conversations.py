"""Lưu hội thoại và tin nhắn trong PostgreSQL.

Hiện chưa có đăng nhập nên mọi hội thoại dùng chung. Khi thêm xác thực, thêm cột
owner_id vào conversations và lọc theo cột đó ở mọi hàm bên dưới.
"""
import uuid

from psycopg.types.json import Jsonb

from .db import query, transaction

DEFAULT_TITLE = "Cuộc trò chuyện mới"
MAX_TITLE = 60
HISTORY_LIMIT = 10

# Chạy lúc khởi động (IF NOT EXISTS) để không cần chạy SQL tay trên database đã có dữ liệu.
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS conversations(
        id UUID PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'Cuộc trò chuyện mới',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages(
        id BIGSERIAL PRIMARY KEY,
        conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user','ai')),
        content TEXT NOT NULL,
        meta JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS messages_conversation_idx ON messages(conversation_id, id)",
    "CREATE INDEX IF NOT EXISTS conversations_updated_idx ON conversations(updated_at DESC)",
]


def ensure_schema():
    with transaction() as cur:
        for statement in SCHEMA:
            cur.execute(statement)


class ConversationNotFound(Exception):
    pass


def parse_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ConversationNotFound(value)


def create(title: str | None = None) -> dict:
    cid = str(uuid.uuid4())
    rows = query(
        "INSERT INTO conversations(id, title) VALUES (%s, %s) "
        "RETURNING id::text AS id, title, created_at, updated_at",
        (cid, (title or DEFAULT_TITLE)[:MAX_TITLE]),
        True,
    )
    return _public(rows[0])


def exists(conversation_id: str) -> bool:
    return bool(query("SELECT 1 FROM conversations WHERE id = %s", (conversation_id,)))


def list_all(limit: int = 100) -> list[dict]:
    rows = query(
        "SELECT id::text AS id, title, created_at, updated_at FROM conversations "
        "ORDER BY updated_at DESC LIMIT %s",
        (limit,),
    )
    return [_public(r) for r in rows]


def messages(conversation_id: str) -> list[dict]:
    if not exists(conversation_id):
        raise ConversationNotFound(conversation_id)
    rows = query(
        "SELECT id, role, content, meta, created_at FROM messages "
        "WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    )
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "text": r["content"],
            "meta": r["meta"] or {},
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


def recent_history(conversation_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    """Các tin nhắn gần nhất theo thứ tự cũ -> mới, dạng {role, text} cho prompt."""
    rows = query(
        "SELECT role, content FROM messages WHERE conversation_id = %s "
        "ORDER BY id DESC LIMIT %s",
        (conversation_id, limit),
    )
    return [{"role": r["role"], "text": r["content"][:12000]} for r in reversed(rows)]


def add_message(conversation_id: str, role: str, content: str, meta: dict | None = None):
    """Thêm tin nhắn. Tin nhắn đầu tiên của người dùng đặt tên hội thoại."""
    with transaction() as cur:
        cur.execute(
            "INSERT INTO messages(conversation_id, role, content, meta) "
            "VALUES (%s, %s, %s, %s)",
            (conversation_id, role, content, Jsonb(meta or {})),
        )
        if role == "user":
            title = " ".join(content.split())[:MAX_TITLE]
            cur.execute(
                "UPDATE conversations SET title = %s, updated_at = NOW() "
                "WHERE id = %s AND title = %s",
                (title, conversation_id, DEFAULT_TITLE),
            )
        cur.execute(
            "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
            (conversation_id,),
        )


def delete(conversation_id: str) -> bool:
    with transaction() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s RETURNING id", (conversation_id,))
        return cur.fetchone() is not None


def _public(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }