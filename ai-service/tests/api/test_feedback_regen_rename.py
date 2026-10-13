"""Đánh giá 👍/👎, sinh lại câu trả lời, đổi tên hội thoại."""
import pytest

from app.core.db import query
from auth_helpers import make_user

pytestmark = pytest.mark.integration


def convo(c, h):
    r = c.post("/conversations", headers=h)
    assert r.status_code == 200
    return r.json()["id"]


def ask(c, h, cid, text, **extra):
    r = c.post("/chat", headers=h, json={"message": text, "use_rag": False, "conversation_id": cid, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def msgs(c, h, cid):
    return c.get(f"/conversations/{cid}/messages", headers=h).json()


def test_chat_returns_message_id_and_history_has_feedback_field(client):
    _, h, _, c = make_user()
    cid = convo(c, h)
    body = ask(c, h, cid, "Xin chào")
    assert isinstance(body["message_id"], int)
    ai = [m for m in msgs(c, h, cid) if m["role"] == "ai"][0]
    assert ai["id"] == body["message_id"] and ai["feedback"] is None


def test_stream_done_has_message_id(client, stream_chat):
    from conftest import parse_sse
    r = client.post("/conversations").json()["id"]
    _, _, body = stream_chat({"message": "chào", "use_rag": False, "conversation_id": r})
    done = [d for e, d in parse_sse(body) if e == "done"][0]
    assert isinstance(done["message_id"], int)


def test_rate_change_and_clear(client):
    _, h, _, c = make_user()
    cid = convo(c, h)
    mid = ask(c, h, cid, "Câu hỏi A")["message_id"]
    url = f"/messages/{mid}/feedback"

    assert c.put(url, headers=h, json={"rating": 1}).json()["rating"] == 1
    assert [m["feedback"] for m in msgs(c, h, cid) if m["role"] == "ai"] == [1]

    r = c.put(url, headers=h, json={"rating": -1, "comment": " Sai số liệu "}).json()
    assert r["rating"] == -1 and r["comment"] == "Sai số liệu"
    assert query("SELECT COUNT(*) AS n FROM message_feedback WHERE message_id = %s", (mid,))[0]["n"] == 1

    assert c.put(url, headers=h, json={"rating": 0}).json()["rating"] is None
    assert [m["feedback"] for m in msgs(c, h, cid) if m["role"] == "ai"] == [None]


def test_feedback_validation_and_ownership(client):
    _, h1, _, c1 = make_user()
    _, h2, _, c2 = make_user()
    cid = convo(c1, h1)
    mid = ask(c1, h1, cid, "Của tôi")["message_id"]
    user_msg = [m for m in msgs(c1, h1, cid) if m["role"] == "user"][0]["id"]

    assert c1.put(f"/messages/{mid}/feedback", headers=h1, json={"rating": 5}).status_code == 422
    assert c2.put(f"/messages/{mid}/feedback", headers=h2, json={"rating": 1}).status_code == 404  # của người khác
    assert c1.put(f"/messages/{user_msg}/feedback", headers=h1, json={"rating": 1}).status_code == 404  # tin của người dùng
    assert c1.put("/messages/99999999/feedback", headers=h1, json={"rating": 1}).status_code == 404
    assert c1.put(f"/messages/{mid}/feedback", json={"rating": 1}).status_code == 401  # chưa đăng nhập


def test_other_user_never_sees_my_rating(client):
    _, h1, _, c1 = make_user()
    cid = convo(c1, h1)
    mid = ask(c1, h1, cid, "Riêng tư")["message_id"]
    c1.put(f"/messages/{mid}/feedback", headers=h1, json={"rating": -1})
    # chủ hội thoại thấy; (người khác không đọc được hội thoại nên không có đường nào lộ ra)
    assert [m["feedback"] for m in msgs(c1, h1, cid) if m["role"] == "ai"] == [-1]


def test_admin_summary_requires_admin_and_lists_downvotes(client):
    _, h, _, c = make_user()
    cid = convo(c, h)
    mid = ask(c, h, cid, "Câu hỏi bị chê duy nhất 7731")["message_id"]
    c.put(f"/messages/{mid}/feedback", headers=h, json={"rating": -1, "comment": "không đúng"})

    assert c.get("/feedback/summary", headers=h).status_code == 403
    s = client.get("/feedback/summary").json()
    assert s["down"] >= 1 and s["rated"] >= 1 and 0 <= s["satisfaction"] <= 1
    mine = [x for x in s["recent_down"] if x["message_id"] == mid]
    assert mine and mine[0]["question"] == "Câu hỏi bị chê duy nhất 7731" and mine[0]["comment"] == "không đúng"


def test_deleting_conversation_removes_feedback(client):
    _, h, _, c = make_user()
    cid = convo(c, h)
    mid = ask(c, h, cid, "Sẽ bị xóa")["message_id"]
    c.put(f"/messages/{mid}/feedback", headers=h, json={"rating": 1})
    c.delete(f"/conversations/{cid}", headers=h)
    assert not query("SELECT 1 FROM message_feedback WHERE message_id = %s", (mid,))


def test_regenerate_replaces_last_exchange(client):
    _, h, _, c = make_user()
    cid = convo(c, h)
    ask(c, h, cid, "Câu một")
    old = ask(c, h, cid, "Câu hai")["message_id"]
    c.put(f"/messages/{old}/feedback", headers=h, json={"rating": -1})

    new = ask(c, h, cid, "Câu hai", regenerate=True)["message_id"]
    texts = [(m["role"], m["text"]) for m in msgs(c, h, cid)]
    assert [t for t in texts if t[0] == "user"] == [("user", "Câu một"), ("user", "Câu hai")]  # không nhân đôi
    assert len(texts) == 4 and new != old
    assert not query("SELECT 1 FROM message_feedback WHERE message_id = %s", (old,))


def test_regenerate_with_wrong_text_deletes_nothing(client):
    _, h, _, c = make_user()
    cid = convo(c, h)
    ask(c, h, cid, "Câu thật")
    ask(c, h, cid, "Câu khác hẳn", regenerate=True)
    assert len(msgs(c, h, cid)) == 4  # thêm lượt mới, không xóa lượt cũ


def test_regenerate_after_stopped_turn(client):
    """Dừng giữa chừng: chỉ còn câu hỏi, không có câu trả lời. Sinh lại không để lại câu hỏi mồ côi."""
    _, h, uid, c = make_user()
    cid = convo(c, h)
    from app.services import conversations
    conversations.add_message(cid, "user", "Bị dừng")
    ask(c, h, cid, "Bị dừng", regenerate=True)
    assert [m["role"] for m in msgs(c, h, cid)] == ["user", "ai"]


def test_rename(client):
    _, h1, _, c1 = make_user()
    _, h2, _, c2 = make_user()
    cid = convo(c1, h1)
    r = c1.put(f"/conversations/{cid}", headers=h1, json={"title": "  Báo cáo   quý 3  "})
    assert r.status_code == 200 and r.json()["title"] == "Báo cáo quý 3"
    assert [x["title"] for x in c1.get("/conversations", headers=h1).json() if x["id"] == cid] == ["Báo cáo quý 3"]

    assert c1.put(f"/conversations/{cid}", headers=h1, json={"title": "   "}).status_code == 422
    assert c1.put(f"/conversations/{cid}", headers=h1, json={"title": ""}).status_code == 422
    assert c2.put(f"/conversations/{cid}", headers=h2, json={"title": "Chiếm quyền"}).status_code == 404
    assert c1.put("/conversations/khong-phai-uuid", headers=h1, json={"title": "x"}).status_code == 404
    long = c1.put(f"/conversations/{cid}", headers=h1, json={"title": "a" * 150}).json()["title"]
    assert len(long) == 60
    # tin nhắn đầu tiên không ghi đè tên đã đặt tay
    ask(c1, h1, cid, "Tin đầu tiên")
    assert [x["title"] for x in c1.get("/conversations", headers=h1).json() if x["id"] == cid] == ["a" * 60]
