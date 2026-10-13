"""Đính kèm file trong chat: lưu thành tài liệu riêng tư, chatbot đọc và phân tích, quyền xem đúng."""
import io
import uuid

import pytest

from app.core.db import query
from auth_helpers import make_user
from conftest import parse_sse

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _app_started(client):  # mở pool DB của ứng dụng (lifespan) cho mọi test trong file
    yield


def doc(text=None, name="bao-cao.txt"):
    text = text or f"Báo cáo nội bộ {uuid.uuid4()}. Doanh thu quý ba đạt 420 triệu, tăng 12% so với quý hai."
    return {"file": (name, text.encode(), "text/plain")}


def attach(c, h, **kw):
    return c.post("/chat/attachments", headers=h, files=doc(**kw))


def test_attach_creates_private_processed_document():
    _, h, uid, c = make_user()
    r = attach(c, h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "processed" and body["chunks"] >= 1 and body["reused"] is False
    row = query("SELECT owner_id::text AS o, status FROM documents WHERE id = %s", (body["id"],))[0]
    assert row["o"] == uid and row["status"] == "processed"


def test_attachment_is_invisible_to_others_but_visible_to_owner_and_admin(client):
    _, h1, _, c1 = make_user()
    _, h2, _, c2 = make_user()
    did = attach(c1, h1).json()["id"]
    assert did in [d["id"] for d in c1.get("/documents", headers=h1).json()]
    mine = [d for d in c1.get("/documents", headers=h1).json() if d["id"] == did][0]
    assert mine["scope"] == "private" and mine["mine"] is True
    assert did not in [d["id"] for d in c2.get("/documents", headers=h2).json()]
    assert c2.get(f"/documents/{did}", headers=h2).status_code == 404
    assert c2.get(f"/documents/{did}/file", headers=h2).status_code == 404
    admin_row = [d for d in client.get("/documents").json() if d["id"] == did]
    assert admin_row and admin_row[0]["owner_email"]  # admin thấy, kèm email người tải lên


def test_group_members_do_not_learn_who_uploaded_a_shared_private_file(client):
    _, h1, _, c1 = make_user()
    _, h2, uid2, c2 = make_user()
    did = attach(c1, h1).json()["id"]
    gid = client.post("/groups", json={"name": "Nhóm email " + uuid.uuid4().hex[:6]}).json()["id"]
    try:
        client.put(f"/groups/{gid}/members", json={"ids": [uid2]})
        client.put(f"/documents/{did}/groups", json={"ids": [gid]})
        row = [d for d in c2.get("/documents", headers=h2).json() if d["id"] == did][0]
        assert "owner_email" not in row and row["scope"] == "group"
    finally:
        client.delete(f"/groups/{gid}")
        client.delete(f"/documents/{did}")


def test_other_user_cannot_use_my_file_as_attachment_or_find_it_in_search(client):
    _, h1, _, c1 = make_user()
    _, h2, _, c2 = make_user()
    token = "riengtu" + uuid.uuid4().hex[:8]
    did = attach(c1, h1, text=f"Tài liệu mật {token} chỉ của tôi. " * 5).json()["id"]
    r = c2.post("/chat", headers=h2, json={"message": "tóm tắt", "attachment_id": did})
    assert r.status_code == 404
    hits = c2.get("/search", headers=h2, params={"q": token, "mode": "keyword"}).json()["results"]
    assert not hits
    assert c1.get("/search", headers=h1, params={"q": token, "mode": "keyword"}).json()["results"]


def test_chat_with_attachment_reads_the_file_and_labels_source_private():
    _, h, _, c = make_user()
    secret = f"MA-{uuid.uuid4().hex[:6]}"
    did = attach(c, h, text=f"Tài liệu thử nghiệm. Mã dự án là {secret}. " * 3).json()["id"]
    cid = c.post("/conversations", headers=h).json()["id"]
    r = c.post("/chat", headers=h, json={"message": "Tóm tắt file này", "use_rag": False,
                                         "conversation_id": cid, "attachment_id": did})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s["document_id"] == did and s["scope"] == "private" for s in body["sources"])
    assert any("attached file" in t["detail"] for t in body["trace"] if t["step"] == "knowledge")
    msgs = c.get(f"/conversations/{cid}/messages", headers=h).json()
    user_msg = [m for m in msgs if m["role"] == "user"][0]
    assert user_msg["meta"]["attachment"]["document_id"] == did  # hiện lại chip file khi mở lại hội thoại


def test_stream_with_attachment(client):
    _, h, _, c = make_user()
    did = attach(c, h).json()["id"]
    with c.stream("POST", "/chat/stream", headers=h, json={"message": "Phân tích file", "attachment_id": did}) as r:
        events = parse_sse("".join(r.iter_text()))
    done = [d for e, d in events if e == "done"][0]
    assert any(s["document_id"] == did for s in done["sources"])


def test_attachment_errors():
    _, h, _, c = make_user()
    assert c.post("/chat", headers=h, json={"message": "x", "attachment_id": "khong-phai-uuid"}).status_code == 404
    assert c.post("/chat", headers=h, json={"message": "x", "attachment_id": str(uuid.uuid4())}).status_code == 404
    assert c.post("/chat/attachments", headers=h, files={"file": ("a.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert c.post("/chat/attachments", headers=h, files={"file": ("a.txt", b"", "text/plain")}).status_code == 422
    big = {"file": ("a.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")}
    assert c.post("/chat/attachments", headers=h, files=big).status_code == 413
    assert c.post("/chat/attachments", files=doc()).status_code == 401


def test_broken_file_is_rejected_and_leaves_nothing_behind():
    _, h, uid, c = make_user()
    r = c.post("/chat/attachments", headers=h, files={"file": ("hong.pdf", b"%PDF-1.4 khong phai pdf that", "application/pdf")})
    assert r.status_code == 422 and r.json()["detail"]
    assert not query("SELECT 1 FROM documents WHERE owner_id = %s", (uid,))


def test_same_file_twice_reuses_and_other_users_do_not_collide():
    _, h1, _, c1 = make_user()
    _, h2, _, c2 = make_user()
    text = f"Nội dung giống hệt nhau {uuid.uuid4()}"
    a = attach(c1, h1, text=text).json()
    b = attach(c1, h1, text=text).json()
    assert b["id"] == a["id"] and b["reused"] is True
    other = attach(c2, h2, text=text)
    assert other.status_code == 201 and other.json()["id"] != a["id"]  # file riêng của A không chặn B


def test_owner_can_delete_but_not_others_and_user_cannot_retry_others(client):
    _, h1, _, c1 = make_user()
    _, h2, _, c2 = make_user()
    did = attach(c1, h1).json()["id"]
    assert c2.delete(f"/documents/{did}", headers=h2).status_code == 403
    assert c2.post(f"/documents/{did}/retry", headers=h2).status_code == 403
    assert c1.delete(f"/documents/{did}", headers=h1).status_code == 200
    assert not query("SELECT 1 FROM documents WHERE id = %s", (did,))


def test_admin_can_publish_private_file_via_group(client):
    _, h1, _, c1 = make_user()
    uemail, h2, uid2, c2 = make_user()
    did = attach(c1, h1).json()["id"]
    gid = client.post("/groups", json={"name": "Nhóm chia sẻ " + uuid.uuid4().hex[:6]}).json()["id"]
    try:
        client.put(f"/groups/{gid}/members", json={"ids": [uid2]})
        client.put(f"/documents/{did}/groups", json={"ids": [gid]})
        assert did in [d["id"] for d in c2.get("/documents", headers=h2).json()]
    finally:
        client.delete(f"/groups/{gid}")
        client.delete(f"/documents/{did}")


def test_deleting_user_removes_private_documents(client):
    _, h, uid, c = make_user()
    did = attach(c, h).json()["id"]
    query("DELETE FROM users WHERE id = %s", (uid,), False)
    assert not query("SELECT 1 FROM documents WHERE id = %s", (did,))


def test_regular_documents_unchanged(client):
    from auth_helpers import add_doc
    _, h, _, c = make_user()
    did = add_doc(client, "Tài liệu công khai " + uuid.uuid4().hex[:6], "Nội dung công khai cho mọi người.")
    try:
        got = [d for d in c.get("/documents", headers=h).json() if d["id"] == did][0]
        assert got["scope"] == "public" and got["mine"] is False
    finally:
        client.delete(f"/documents/{did}")


def test_pasting_same_content_twice_is_rejected_not_duplicated(client):
    text = f"Nội dung dán lặp lại {uuid.uuid4()}"
    first = client.post("/documents", json={"title": "Bản một", "content": text})
    assert first.status_code == 200, first.text
    try:
        again = client.post("/documents", json={"title": "Bản hai", "content": text})
        assert again.status_code == 409 and "đã được index" in again.json()["detail"]
        assert query("SELECT COUNT(*)::int AS n FROM documents WHERE content_hash IS NOT NULL AND title IN ('Bản một','Bản hai') "
                     "AND id = %s", (first.json()["id"],))[0]["n"] == 1
    finally:
        client.delete(f"/documents/{first.json()['id']}")
    # xóa rồi thì dán lại được
    redo = client.post("/documents", json={"title": "Bản ba", "content": text})
    assert redo.status_code == 200
    client.delete(f"/documents/{redo.json()['id']}")


def test_concurrent_identical_pastes_create_only_one(client):
    from concurrent.futures import ThreadPoolExecutor
    text = f"Hai request cùng lúc {uuid.uuid4()}"

    def post(_):
        return client.post("/documents", json={"title": "Song song", "content": text})

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(post, range(4)))
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1 and all(c in (200, 409) for c in codes), codes
    for r in results:
        if r.status_code == 200:
            client.delete(f"/documents/{r.json()['id']}")
