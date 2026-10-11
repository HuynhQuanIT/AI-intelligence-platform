"""Nhóm người dùng và quyền xem tài liệu theo nhóm (xem rag/access.py cho quy tắc hiển thị)."""
import uuid

from ..core.db import query, transaction

MAX_NAME = 80


class GroupError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS groups(
        id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS groups_name_idx ON groups(lower(name))",
    """
    CREATE TABLE IF NOT EXISTS user_groups(
        group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        PRIMARY KEY (group_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS user_groups_user_idx ON user_groups(user_id)",
    """
    CREATE TABLE IF NOT EXISTS document_groups(
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        PRIMARY KEY (document_id, group_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS document_groups_group_idx ON document_groups(group_id)",
]


def ensure_schema() -> None:
    with transaction() as cur:
        for statement in SCHEMA:
            cur.execute(statement)


def _uuid(value: str, what: str = "nhóm") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise GroupError(404, f"Không tìm thấy {what}.")


def _row(r: dict) -> dict:
    return {"id": str(r["id"]), "name": r["name"], "description": r["description"],
            "member_count": r.get("member_count", 0), "document_count": r.get("document_count", 0),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None}


def list_groups() -> list[dict]:
    rows = query(
        """
        SELECT g.*,
               (SELECT COUNT(*) FROM user_groups ug WHERE ug.group_id = g.id)::int AS member_count,
               (SELECT COUNT(*) FROM document_groups dg WHERE dg.group_id = g.id)::int AS document_count
        FROM groups g ORDER BY lower(g.name)
        """
    )
    return [_row(r) for r in rows]


def get_group(group_id: str) -> dict:
    gid = _uuid(group_id)
    rows = query("SELECT * FROM groups WHERE id = %s", (gid,))
    if not rows:
        raise GroupError(404, "Không tìm thấy nhóm.")
    members = query(
        "SELECT u.id::text AS id, u.email FROM user_groups ug JOIN users u ON u.id = ug.user_id "
        "WHERE ug.group_id = %s ORDER BY u.email", (gid,))
    docs = query(
        "SELECT d.id::text AS id, d.title FROM document_groups dg JOIN documents d ON d.id = dg.document_id "
        "WHERE dg.group_id = %s ORDER BY d.title", (gid,))
    return {**_row({**rows[0], "member_count": len(members), "document_count": len(docs)}),
            "members": members, "documents": docs}


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > MAX_NAME:
        raise GroupError(422, f"Tên nhóm cần từ 1 đến {MAX_NAME} ký tự.")
    return name


def create_group(name: str, description: str = "") -> dict:
    name = _clean_name(name)
    gid = str(uuid.uuid4())
    try:
        query("INSERT INTO groups(id, name, description) VALUES (%s, %s, %s)",
              (gid, name, (description or "").strip()[:500]), False)
    except Exception as exc:
        if "groups_name_idx" in str(exc) or "unique" in str(exc).lower():
            raise GroupError(409, "Đã có nhóm trùng tên.")
        raise
    return get_group(gid)


def update_group(group_id: str, name: str, description: str = "") -> dict:
    gid = get_group(group_id)["id"]
    name = _clean_name(name)
    try:
        query("UPDATE groups SET name = %s, description = %s WHERE id = %s",
              (name, (description or "").strip()[:500], gid), False)
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise GroupError(409, "Đã có nhóm trùng tên.")
        raise
    return get_group(gid)


def delete_group(group_id: str) -> None:
    """Không xóa nhóm nếu có tài liệu chỉ thuộc nhóm này: xóa sẽ vô tình biến tài liệu thành công khai."""
    gid = get_group(group_id)["id"]
    only = query(
        """
        SELECT d.title FROM document_groups dg JOIN documents d ON d.id = dg.document_id
        WHERE dg.group_id = %s
          AND (SELECT COUNT(*) FROM document_groups x WHERE x.document_id = dg.document_id) = 1
        ORDER BY d.title
        """, (gid,))
    if only:
        names = ", ".join(r["title"] for r in only[:3])
        raise GroupError(409, f"Nhóm đang là nhóm duy nhất của {len(only)} tài liệu ({names}). "
                              "Hãy gán nhóm khác cho các tài liệu đó trước.")
    query("DELETE FROM groups WHERE id = %s", (gid,), False)


def set_members(group_id: str, user_ids: list[str]) -> dict:
    gid = get_group(group_id)["id"]
    ids = list(dict.fromkeys(_uuid(u, "người dùng") for u in user_ids))
    if ids:
        found = {r["id"] for r in query("SELECT id::text AS id FROM users WHERE id = ANY(%s::uuid[])", (ids,))}
        if found != set(ids):
            raise GroupError(404, "Có người dùng không tồn tại.")
    with transaction() as cur:
        cur.execute("DELETE FROM user_groups WHERE group_id = %s", (gid,))
        cur.executemany("INSERT INTO user_groups(group_id, user_id) VALUES (%s, %s)", [(gid, u) for u in ids])
    return get_group(gid)


def set_document_groups(document_id: str, group_ids: list[str]) -> list[dict]:
    """Danh sách rỗng = tài liệu công khai cho mọi người đã đăng nhập."""
    did = _uuid(document_id, "tài liệu")
    if not query("SELECT 1 FROM documents WHERE id = %s", (did,)):
        raise GroupError(404, "Không tìm thấy tài liệu.")
    ids = list(dict.fromkeys(_uuid(g) for g in group_ids))
    if ids:
        found = {r["id"] for r in query("SELECT id::text AS id FROM groups WHERE id = ANY(%s::uuid[])", (ids,))}
        if found != set(ids):
            raise GroupError(404, "Có nhóm không tồn tại.")
    with transaction() as cur:
        cur.execute("DELETE FROM document_groups WHERE document_id = %s", (did,))
        cur.executemany("INSERT INTO document_groups(document_id, group_id) VALUES (%s, %s)",
                        [(did, g) for g in ids])
    return groups_of_documents([did]).get(did, [])


def groups_of_documents(document_ids: list[str]) -> dict[str, list[dict]]:
    if not document_ids:
        return {}
    rows = query(
        "SELECT dg.document_id::text AS document_id, g.id::text AS id, g.name FROM document_groups dg "
        "JOIN groups g ON g.id = dg.group_id WHERE dg.document_id = ANY(%s::uuid[]) ORDER BY lower(g.name)",
        (list(document_ids),))
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["document_id"], []).append({"id": r["id"], "name": r["name"]})
    return out


def groups_of_user(user_id) -> list[dict]:
    return [{"id": r["id"], "name": r["name"]} for r in query(
        "SELECT g.id::text AS id, g.name FROM user_groups ug JOIN groups g ON g.id = ug.group_id "
        "WHERE ug.user_id = %s ORDER BY lower(g.name)", (str(user_id),))]
