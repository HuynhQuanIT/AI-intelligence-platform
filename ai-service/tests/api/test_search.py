"""Tìm kiếm tài liệu: từ khóa/ngữ nghĩa/kết hợp, tô sáng không phân biệt dấu, tôn trọng quyền xem theo nhóm."""
import uuid

import pytest

from app.services import ratelimit
from app.services.search import snippet_with_marks
from auth_helpers import add_doc, make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_limits(client):
    ratelimit.reset()
    yield


def find(client, q, headers=None, **params):
    r = client.get("/search", params={"q": q, **params}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_snippet_marks_are_accent_insensitive_and_exact():
    s = snippet_with_marks("Mẫu thử phải được bảo quản ở nhiệt độ âm tám mươi độ.", {"bao", "quan"})
    shown = [s["text"][a:b] for a, b in s["marks"]]
    assert shown == ["bảo", "quản"]


def test_snippet_window_centers_on_first_match_in_long_text():
    text = ("lorem " * 200) + "ZEBRAFISH tìm thấy ở đây " + ("ipsum " * 200)
    s = snippet_with_marks(text, {"zebrafish"})
    assert s["before"] and s["after"] and len(s["text"]) <= 262
    assert [s["text"][a:b] for a, b in s["marks"]] == ["ZEBRAFISH"]


def test_keyword_search_finds_by_content_not_only_title(client):
    tag = uuid.uuid4().hex[:8]
    did = add_doc(client, f"Tiêu đề không liên quan {tag}", f"Quy trình narwhal{tag} bảo quản mẫu ở âm tám mươi độ")
    try:
        data = find(client, f"narwhal{tag}", mode="keyword")
        top = data["results"][0]
        assert top["document_id"] == did and top["scope"] == "public"
        m = top["matches"][0]
        assert f"narwhal{tag}" in m["snippet"]["text"] and m["snippet"]["marks"]
        assert top["relevance"] == 1.0
    finally:
        client.delete(f"/documents/{did}")


def test_semantic_mode_without_embeddings_falls_back_with_note(client):
    tag = uuid.uuid4().hex[:8]
    did = add_doc(client, f"Tài liệu {tag}", f"Nội dung okapi{tag} dùng để thử")
    try:
        data = find(client, f"okapi{tag}", mode="semantic")
        assert data["mode"] == "semantic" and data["mode_used"] == "keyword" and "Embedding" in data["note"]
        assert data["results"][0]["document_id"] == did
    finally:
        client.delete(f"/documents/{did}")


def test_search_respects_groups_and_labels(client):
    tag = uuid.uuid4().hex[:8]
    gid = client.post("/groups", json={"name": f"Nhóm tìm {tag}"}).json()["id"]
    _, hm, uidm, cm = make_user()
    _, ho, _, co = make_user()
    client.put(f"/groups/{gid}/members", json={"ids": [uidm]})
    sec = add_doc(client, f"Bí mật {tag}", f"axolotl{tag} nội dung chỉ nhóm được xem")
    client.put(f"/documents/{sec}/groups", json={"ids": [gid]})
    try:
        assert [d["document_id"] for d in find(cm, f"axolotl{tag}", hm, mode="keyword")["results"]] == [sec]
        assert find(co, f"axolotl{tag}", ho, mode="keyword")["results"] == []          # người ngoài nhóm: không thấy
        hit = find(cm, f"axolotl{tag}", hm, mode="keyword")["results"][0]
        assert hit["scope"] == "group" and [g["id"] for g in hit["groups"]] == [gid]
        # lọc theo nhóm
        assert find(client, f"axolotl{tag}", mode="keyword", group_id=gid)["total"] == 1
        other = client.post("/groups", json={"name": f"Nhóm khác {tag}"}).json()["id"]
        assert find(client, f"axolotl{tag}", mode="keyword", group_id=other)["total"] == 0
    finally:
        client.delete(f"/documents/{sec}")


def test_search_validation_and_auth(client):
    assert client.get("/search", params={"q": "a"}).status_code == 422
    assert client.get("/search", params={"q": "hợp lệ", "mode": "xxx"}).status_code == 422
    assert client.get("/search", params={"q": "hợp lệ", "group_id": "khong-phai-uuid"}).status_code == 404
    from auth_helpers import new_client
    assert new_client().get("/search", params={"q": "hợp lệ"}).status_code == 401
