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
    "ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
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


def apply_members(group_id: str, user_ids: list[str]) -> tuple[dict, list[dict]]:
    """Đặt danh sách thành viên theo kiểu so sánh (giữ nguyên added_at của người đã có).
    Trả (nhóm, [{id, email}] những người MỚI được thêm) để gửi thông báo."""
    group = get_group(group_id)
    gid = group["id"]
    ids = list(dict.fromkeys(_uuid(u, "người dùng") for u in user_ids))
    if ids:
        found = {r["id"] for r in query("SELECT id::text AS id FROM users WHERE id = ANY(%s::uuid[])", (ids,))}
        if found != set(ids):
            raise GroupError(404, "Có người dùng không tồn tại.")
    current = {m["id"] for m in group["members"]}
    added = [u for u in ids if u not in current]
    removed = [u for u in current if u not in set(ids)]
    with transaction() as cur:
        if removed:
            cur.execute("DELETE FROM user_groups WHERE group_id = %s AND user_id = ANY(%s::uuid[])", (gid, removed))
        if added:
            cur.executemany("INSERT INTO user_groups(group_id, user_id) VALUES (%s, %s)", [(gid, u) for u in added])
    new_users = query("SELECT id::text AS id, email FROM users WHERE id = ANY(%s::uuid[])", (added,)) if added else []
    return get_group(gid), new_users


def set_members(group_id: str, user_ids: list[str]) -> dict:
    return apply_members(group_id, user_ids)[0]


def membership_mail(email: str, group: dict) -> tuple[str, str, str]:
    n = group["document_count"]
    docs = f"Nhờ vậy bạn xem được thêm {n} tài liệu của nhóm này trong Knowledge Center và chatbot sẽ dùng chúng khi trả lời bạn." \
        if n else "Hiện nhóm chưa có tài liệu riêng; khi có, bạn sẽ xem được ngay."
    return (email, f"Bạn đã được thêm vào nhóm {group['name']}",
            f"Quản trị viên vừa thêm bạn vào nhóm \"{group['name']}\". {docs}\n"
            "Xem nhóm của bạn ở trang My Account.")


def access_summary(user: dict) -> dict:
    """Thông tin để người dùng biết mình thuộc nhóm nào và đang xem được bao nhiêu tài liệu."""
    from ..rag.access import viewer_of, visible_sql
    cond, params = visible_sql(viewer_of(user), "d")
    total = query(f"SELECT COUNT(*)::int AS n FROM documents d WHERE {cond}", params)[0]["n"]
    mine = [] if user.get("role") == "admin" else [
        {"id": r["id"], "name": r["name"], "description": r["description"], "document_count": r["document_count"],
         "added_at": r["added_at"].isoformat() if r["added_at"] else None}
        for r in query(
            """
            SELECT g.id::text AS id, g.name, g.description, ug.added_at,
                   (SELECT COUNT(*) FROM document_groups dg WHERE dg.group_id = g.id)::int AS document_count
            FROM user_groups ug JOIN groups g ON g.id = ug.group_id
            WHERE ug.user_id = %s ORDER BY lower(g.name)
            """, (str(user["id"]),))]
    in_groups = sum(g["document_count"] for g in mine)
    return {"groups": mine, "visible_documents": total, "group_documents": in_groups}


def mark_documents_for(user: dict, rows: list[dict]) -> list[dict]:
    """Gắn scope (public|group) và chỉ các nhóm CỦA CHÍNH người dùng vào từng tài liệu."""
    by_doc = groups_of_documents([r["id"] for r in rows])
    mine = {g["id"] for g in groups_of_user(user["id"])}
    out = []
    for r in rows:
        all_groups = by_doc.get(r["id"], [])
        out.append({**r, "scope": "group" if all_groups else "public",
                    "groups": [g for g in all_groups if g["id"] in mine]})
    return out


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


def label_sources(viewer: dict | None, sources: list) -> list:
    """Gắn scope (public|group) và nhóm vào từng nguồn trích dẫn.
    Admin thấy mọi nhóm của tài liệu; người dùng thường chỉ thấy nhóm CỦA MÌNH (không lộ nhóm khác)."""
    ids = list({x["document_id"] for x in sources if x.get("document_id")})
    if not ids:
        return sources
    by_doc = groups_of_documents(ids)
    viewer = viewer or {}
    if viewer.get("admin"):
        mine = None  # None = không lọc
    elif viewer.get("user_id"):
        mine = {g["id"] for g in groups_of_user(viewer["user_id"])}
    else:
        mine = set()
    out = []
    for x in sources:
        found = by_doc.get(x.get("document_id"), [])
        shown = found if mine is None else [g for g in found if g["id"] in mine]
        out.append({**x, "scope": "group" if found else "public", "groups": shown})
    return out
