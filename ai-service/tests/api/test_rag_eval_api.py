"""Trang admin "RAG Evaluation": đo truy xuất trên tài liệu thật theo bộ câu hỏi nhập từ giao diện."""
import uuid

import pytest

from auth_helpers import make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _app_started(client):
    yield


def body(doc, tag="", **kw):
    return {"questions": [
        {"q": f"Mã số bảo mật của phòng kho {tag} là gì?", "tier": "lexical", "doc": doc, "fact": "mã số bảo mật phòng kho"},
        {"q": "Hôm nay thời tiết ở Hà Nội thế nào?", "tier": "negative"},
    ], **kw}


def test_requires_admin():
    _, h, _, c = make_user()
    assert c.post("/rag-eval", headers=h, json=body("x")).status_code == 403


def test_runs_on_real_document_and_reports_metrics():
    _, h, _, c = make_user(role="admin")
    tag = uuid.uuid4().hex[:8]
    title = f"Quy định kho {tag}"
    r = c.post("/documents", headers=h, json={
        "title": title, "content": f"Quy định kho {tag}. Mã số bảo mật phòng kho do trưởng kho giữ và đổi mỗi tháng."})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    try:
        r = c.post("/rag-eval", headers=h, json=body(title, tag))
        assert r.status_code == 200, r.text
        out = r.json()
        res = out["results"][0]
        assert res["metrics"]["lexical"]["n"] == 1 and res["metrics"]["lexical"]["hit@4"] == 1.0
        assert res["metrics"]["negative"]["rejection"] == 1.0
        assert out["failures"] == [] and "semantic_enabled" in out
        both = c.post("/rag-eval", headers=h, json={**body(title, tag), "compare": True}).json()
        assert [x["reranker"] for x in both["results"]] == ["off", "heuristic"]
    finally:
        c.delete(f"/documents/{doc_id}", headers=h)


def test_unknown_document_and_missing_fact_are_422_with_message():
    _, h, _, c = make_user(role="admin")
    r = c.post("/rag-eval", headers=h, json=body("Không có tài liệu này"))
    assert r.status_code == 422 and "Không thấy tài liệu" in r.json()["detail"]
    bad = {"questions": [{"q": "Câu hỏi", "tier": "lexical"}]}
    r = c.post("/rag-eval", headers=h, json=bad)
    assert r.status_code == 422 and "Câu 1" in r.json()["detail"]


def test_reports_top_similarity_before_gate(monkeypatch):
    """Có embeddings: kết quả kèm độ giống cao nhất (trước cổng) để hiệu chỉnh MIN_TOP_SIMILARITY."""
    from app.rag import embeddings, retrieval

    monkeypatch.setattr(embeddings, "enabled", lambda: True)
    monkeypatch.setattr(retrieval, "retrieve_vector", lambda q, limit, viewer=None: [
        {"title": "T", "content": "c", "document_id": "d", "chunk_index": 0, "similarity": 0.55}])
    _, info = retrieval.retrieve_ex("câu hỏi bất kỳ", 4)
    assert info["top_similarity"] == 0.55 and info["mode"] == "hybrid"

    _, h, _, c = make_user(role="admin")
    out = c.post("/rag-eval", headers=h, json={"questions": [
        {"q": "Thủ đô của nước Pháp là gì?", "tier": "negative"}]}).json()
    assert out["min_top_similarity"] == retrieval.MIN_TOP_SIMILARITY
    row = out["results"][0]["rows"][0]
    assert row["sim"] == 0.55 and out["results"][0]["similarity"]["max_irrelevant"] == 0.55


def test_lexical_alone_requires_matching_accents(monkeypatch):
    """Vector không thấy gì giống: từ khóa một mình không được khớp qua việc bỏ dấu ('thủ' ~ 'thu')."""
    from app.rag import embeddings, retrieval
    from app.rag.access import ADMIN

    monkeypatch.setattr(embeddings, "enabled", lambda: True)
    monkeypatch.setattr(retrieval, "retrieve_vector", lambda q, limit, viewer=None: [
        {"title": "T", "content": "c", "document_id": "d", "chunk_index": 0, "similarity": 0.58}])  # dưới cổng 0.67, trên 0.55
    _, h, _, c = make_user(role="admin")
    tag = uuid.uuid4().hex[:6]
    r = c.post("/documents", headers=h, json={
        "title": f"Biên bản {tag}",
        "content": f"Biên bản thu thập thông tin {tag}: nước sạch, tuân theo pháp luật hiện hành."})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    def titles(q):
        hits, _ = retrieval.retrieve_ex(q, 4, ADMIN, rerank="off")
        return [x["title"] for x in hits]

    try:
        assert f"Biên bản {tag}" not in titles("Thủ đô của nước Pháp là gì?")   # thu thập ≠ thủ (đều là "thu" khi bỏ dấu)
        assert f"Biên bản {tag}" in titles(f"thu thap thong tin {tag}")        # gõ không dấu vẫn tìm được
    finally:
        c.delete(f"/documents/{doc_id}", headers=h)


def test_keywords_cannot_rescue_when_vector_sees_nothing_related(monkeypatch):
    """Vector thấy độ giống rất thấp: các từ khóa chung trùng ngẫu nhiên (đủ cả dấu) cũng không được trả nguồn."""
    from app.rag import embeddings, retrieval
    from app.rag.access import ADMIN

    monkeypatch.setattr(embeddings, "enabled", lambda: True)
    sim = {"v": 0.52}
    monkeypatch.setattr(retrieval, "retrieve_vector", lambda q, limit, viewer=None: [
        {"title": "T", "content": "c", "document_id": "d", "chunk_index": 0, "similarity": sim["v"]}])
    _, h, _, c = make_user(role="admin")
    tag = uuid.uuid4().hex[:6]
    r = c.post("/documents", headers=h, json={
        "title": f"An toàn {tag}",
        "content": f"Quy trình an toàn {tag}: mọi người tuân thủ nội quy, nước uống đủ, theo pháp luật hiện hành."})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    q = "Thủ đô của nước Pháp là gì?"   # thủ, nước, pháp đều có (đủ dấu) trong tài liệu trên
    try:
        hits, _ = retrieval.retrieve_ex(q, 4, ADMIN, rerank="off")
        assert f"An toàn {tag}" not in [x["title"] for x in hits]
        sim["v"] = 0.58   # vector chưa bác bỏ hẳn: từ khóa được phép cứu
        hits, _ = retrieval.retrieve_ex(q, 4, ADMIN, rerank="off")
        assert f"An toàn {tag}" in [x["title"] for x in hits]
    finally:
        c.delete(f"/documents/{doc_id}", headers=h)
