"""Tìm kiếm tài liệu cho người dùng: từ khóa, ngữ nghĩa (vector) hoặc kết hợp. Dùng lại tầng truy xuất của RAG
nên luôn tôn trọng quyền xem theo nhóm (rag/access.py)."""
import logging
import re
import time
import unicodedata

from ..core.db import query
from ..rag import embeddings, retrieval
from ..rag.text import keywords
from . import groups

logger = logging.getLogger(__name__)

MODES = ("hybrid", "keyword", "semantic")
CHUNKS_PER_DOC = 3
SNIPPET_WIDTH = 260


def _fold(text: str) -> str:
    """Bỏ dấu + chữ thường nhưng GIỮ NGUYÊN độ dài (1 ký tự -> 1 ký tự) để vị trí khớp với văn bản gốc."""
    out = []
    for ch in text:
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn")
        base = base.lower().replace("đ", "d")
        out.append(base[:1] or " ")
    return "".join(out)


def snippet_with_marks(content: str, terms: set[str], width: int = SNIPPET_WIDTH) -> dict:
    """Cắt đoạn trích quanh chỗ khớp đầu tiên và trả các khoảng cần tô sáng [bắt đầu, kết thúc)."""
    content = content or ""
    folded = _fold(content)
    spans = [(m.start(), m.end()) for m in re.finditer(r"\w+", folded) if m.group() in terms]
    start = max(0, spans[0][0] - width // 3) if spans else 0
    if start:
        space = content.find(" ", start)
        start = space + 1 if 0 <= space < start + 25 else start
    end = min(len(content), start + width)
    if end < len(content):
        space = content.rfind(" ", start, end)
        end = space if space > start + width // 2 else end
    text = content[start:end].strip()
    shift = start + (len(content[start:end]) - len(content[start:end].lstrip()))
    marks = [[a - shift, b - shift] for a, b in spans if a >= shift and b <= shift + len(text)]
    return {
        "text": text, "marks": marks,
        "before": start > 0, "after": end < len(content),
    }


def _gate_semantic(hits: list[dict]) -> list[dict]:
    """Cùng cổng với chatbot: chunk giống nhất phải đủ giống thì mới coi là có kết quả; bỏ chunk dưới sàn."""
    if not hits or hits[0]["similarity"] < retrieval.MIN_TOP_SIMILARITY:
        return []
    return [h for h in hits if h["similarity"] >= retrieval.MIN_SIMILARITY]


def _run(q: str, mode: str, limit: int, viewer: dict) -> tuple[list[dict], str, str]:
    """Trả (các chunk xếp hạng, chế độ đã dùng thực tế, ghi chú cho người dùng)."""
    note = ""
    if mode != "keyword" and not embeddings.enabled():
        return retrieval.retrieve_lexical(q, limit, viewer), "keyword", \
            "Embedding đang tắt nên chỉ tìm được theo từ khóa (cần LLM_PROVIDER=gemini để tìm theo ngữ nghĩa)."
    if mode == "keyword":
        return retrieval.retrieve_lexical(q, limit, viewer), "keyword", note
    if mode == "semantic":
        try:
            hits = _gate_semantic(retrieval.retrieve_vector(q, limit, viewer))
            return [{**h, "score": h["similarity"]} for h in hits], "semantic", note
        except Exception:
            logger.exception("Tìm kiếm ngữ nghĩa lỗi, quay về từ khóa")
            return retrieval.retrieve_lexical(q, limit, viewer), "keyword", \
                "Tìm theo ngữ nghĩa đang lỗi nên tạm dùng từ khóa."
    hits, info = retrieval.retrieve_ex(q, limit, viewer)
    if info["mode"] == "keyword":
        note = "Tìm theo ngữ nghĩa không dùng được lúc này, kết quả chỉ theo từ khóa."
    return hits, info["mode"], note


def search(q: str, mode: str, limit_docs: int, viewer: dict, group_id: str | None = None) -> dict:
    started = time.monotonic()
    terms = keywords(q)
    chunk_limit = limit_docs * 6 if group_id else limit_docs * 4
    hits, used, note = _run(q, mode, chunk_limit, viewer)

    if group_id:
        ids = [h["document_id"] for h in hits]
        keep = {r["document_id"] for r in query(
            "SELECT document_id::text AS document_id FROM document_groups "
            "WHERE group_id = %s AND document_id = ANY(%s::uuid[])", (group_id, ids))} if ids else set()
        hits = [h for h in hits if h["document_id"] in keep]

    # Gộp theo tài liệu: điểm của tài liệu = điểm chunk tốt nhất; giữ tối đa vài đoạn khớp.
    docs: dict[str, dict] = {}
    for h in hits:
        d = docs.setdefault(h["document_id"], {
            "document_id": h["document_id"], "title": h["title"], "score": h["score"], "matches": []})
        if len(d["matches"]) < CHUNKS_PER_DOC:
            d["matches"].append({
                "chunk_index": h["chunk_index"], "similarity": h.get("similarity"),
                "snippet": snippet_with_marks(h["content"], terms),
            })
    ranked = sorted(docs.values(), key=lambda d: d["score"], reverse=True)[:limit_docs]

    top = max((d["score"] for d in ranked), default=0) or 1
    names = {r["id"]: r["filename"] for r in query(
        "SELECT id::text AS id, filename FROM documents WHERE id = ANY(%s::uuid[])",
        ([d["document_id"] for d in ranked],))} if ranked else {}
    for d in ranked:
        d["relevance"] = round(d["score"] / top, 3)  # tương đối so với kết quả tốt nhất
        d["filename"] = names.get(d["document_id"])
    ranked = groups.label_sources(viewer, ranked)

    return {
        "query": q, "mode": mode, "mode_used": used, "note": note,
        "took_ms": int((time.monotonic() - started) * 1000),
        "total": len(ranked), "results": ranked,
    }
