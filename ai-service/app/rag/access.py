"""Quyền xem tài liệu theo nhóm.

Quy tắc duy nhất, dùng chung cho danh sách, xem, tải file, tìm kiếm RAG và công cụ của agent:
  - tài liệu KHÔNG thuộc nhóm nào: mọi người đã đăng nhập đều thấy;
  - tài liệu thuộc >= 1 nhóm: chỉ thành viên của một trong các nhóm đó (và admin) thấy.
Người xem là dict nhỏ (JSON được, đi qua state của LangGraph). Mặc định an toàn nhất: PUBLIC_ONLY.
"""

ADMIN = {"admin": True, "user_id": None}
PUBLIC_ONLY = {"admin": False, "user_id": None}


def viewer_of(user: dict) -> dict:
    if user.get("role") == "admin":
        return ADMIN
    return {"admin": False, "user_id": str(user["id"])}


def visible_sql(viewer: dict | None, alias: str = "d") -> tuple[str, tuple]:
    """Trả (điều kiện SQL, tham số) để ghép vào WHERE của truy vấn trên bảng documents."""
    viewer = viewer or PUBLIC_ONLY
    if viewer.get("admin"):
        return "TRUE", ()

    done = f"{alias}.status = 'processed'"  # tài liệu đang xử lý/lỗi chỉ admin thấy
    no_group = f"NOT EXISTS (SELECT 1 FROM document_groups dg WHERE dg.document_id = {alias}.id)"
    user_id = viewer.get("user_id")
    if not user_id:
        return f"({done} AND {no_group})", ()

    member = (
        "EXISTS (SELECT 1 FROM document_groups dg JOIN user_groups ug ON ug.group_id = dg.group_id "
        f"WHERE dg.document_id = {alias}.id AND ug.user_id = %s)"
    )
    return f"({done} AND ({no_group} OR {member}))", (user_id,)
