"""Truy xuất ngữ cảnh: từ khóa + vector (pgvector) gộp bằng Reciprocal Rank Fusion."""
import logging
import os
from functools import lru_cache

from ..core.db import query
from . import embeddings
from .text import keywords, normalize_text, words

logger = logging.getLogger(__name__)


def retrieve_lexical(question, limit=4):
    rows = query(
        """
        SELECT
            d.title,
            c.content,
            c.document_id,
            c.chunk_index
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'processed'
        """
    )

    question_normalized = normalize_text(question)
    question_words = keywords(question)

    ranked = []

    for row in rows:
        title = row["title"] or ""
        content = row["content"] or ""

        title_normalized = normalize_text(title)
        title_words = words(title)
        content_words = words(content)

        # Điểm khớp từ khóa trong nội dung
        content_score = (
            len(question_words & content_words)
            / max(1, len(question_words))
        )

        # Điểm khớp từ khóa trong tên tài liệu
        title_score = (
            len(question_words & title_words)
            / max(1, len(question_words))
        )

        # Ưu tiên khi tên tài liệu xuất hiện trong câu hỏi
        title_bonus = 0.0

        if title_normalized and title_normalized in question_normalized:
            title_bonus = 0.5

        score = content_score + (title_score * 0.5) + title_bonus

        if score > 0:
            ranked.append((score, row))

    ranked.sort(
        key=lambda item: item[0],
        reverse=True
    )

    return [
        {
            "title": row["title"],
            "content": row["content"],
            "score": round(score, 3),
            "document_id": str(row["document_id"]),
            "chunk_index": row["chunk_index"]
        }
        for score, row in ranked[:limit]
    ]


RRF_K = 60
# Vector là tín hiệu chính, từ khóa chỉ hỗ trợ (trọng số thấp hơn).
SEMANTIC_WEIGHT = float(os.getenv("RRF_SEMANTIC_WEIGHT", "1.0"))
LEXICAL_WEIGHT = float(os.getenv("RRF_LEXICAL_WEIGHT", "0.5"))
# Chỉ giữ kết quả vector có độ giống cách kết quả tốt nhất không quá ngần này.
# Dùng ngưỡng tương đối vì độ giống tuyệt đối thay đổi theo model và ngôn ngữ.
SEMANTIC_MARGIN = float(os.getenv("SEMANTIC_MARGIN", "0.12"))
# Đo thực tế với gemini-embedding-001 (768 chiều) trên 12 câu hỏi:
#   chunk giống nhất của câu LIÊN QUAN:      0.70 - 0.85 (thấp nhất 0.702)
#   chunk giống nhất của câu KHÔNG LIÊN QUAN: 0.52 - 0.64 (cao nhất 0.638)
# Câu tiếng Việt cho nhiễu cao hơn tiếng Anh. Chưa hiệu chỉnh cho corpus lớn hơn: đo lại khi dữ liệu đổi.
# Cổng: nếu chunk giống nhất còn dưới ngưỡng này thì coi như không có tài liệu liên quan.
MIN_TOP_SIMILARITY = float(os.getenv("MIN_TOP_SIMILARITY", "0.67"))
# Sàn cho từng chunk phụ khi đã qua cổng.
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.60"))
# Khi chạy hybrid, kết quả chỉ khớp từ khóa phải khớp ít nhất ngần này tỉ lệ từ khóa của câu hỏi.
LEXICAL_MIN_SCORE = float(os.getenv("LEXICAL_MIN_SCORE", "0.5"))
# Khi vector không tìm thấy gì đủ giống, từ khóa phải khớp (gần) toàn bộ mới được tin một mình.
# Tránh câu ngoài chủ đề lọt vào chỉ vì trùng vài từ chung như "cong thuc", "bo".
LEXICAL_ALONE_MIN_SCORE = float(os.getenv("LEXICAL_ALONE_MIN_SCORE", "1.0"))


@lru_cache(maxsize=256)
def _query_vector(question: str) -> str:
    """Nhớ vector của câu hỏi đã hỏi: giảm lượt gọi API embedding (hạn mức) và độ trễ.
    Lỗi không được lưu đệm nên lần sau vẫn thử lại."""
    return embeddings.to_pgvector(
        embeddings.embed_texts([question], "RETRIEVAL_QUERY")[0]
    )


def retrieve_vector(question, limit):
    vec = _query_vector(question)

    rows = query(
        """
        SELECT
            d.title,
            c.content,
            c.document_id,
            c.chunk_index,
            1 - (c.embedding <=> %s::vector) AS similarity
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'processed' AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
        """,
        (vec, vec, limit),
    )

    return [
        {
            "title": r["title"],
            "content": r["content"],
            "document_id": str(r["document_id"]),
            "chunk_index": r["chunk_index"],
            "similarity": round(float(r["similarity"]), 3),
        }
        for r in rows
    ]


def near_top(semantic):
    """Qua cổng chunk tốt nhất, bỏ chunk dưới sàn, rồi bỏ những chunk kém xa chunk tốt nhất
    (danh sách đã sắp giảm dần)."""
    if not semantic or semantic[0]["similarity"] < MIN_TOP_SIMILARITY:
        return []
    semantic = [item for item in semantic if item["similarity"] >= MIN_SIMILARITY]
    cutoff = semantic[0]["similarity"] - SEMANTIC_MARGIN
    return [item for item in semantic if item["similarity"] >= cutoff]


def _describe_error(exc) -> str:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return type(exc).__name__ + (f" {code}" if code else "")


def retrieve_ex(question, limit=4):
    """
    Hybrid: từ khóa + vector, gộp bằng Reciprocal Rank Fusion có trọng số.
    Trả (kết quả, info). info cho biết đã dùng cách nào và vì sao quay về từ khóa,
    để trace không che giấu việc vector search bị lỗi.
    """
    lexical = retrieve_lexical(question, limit * 3)

    if not embeddings.enabled():
        return lexical[:limit], {"mode": "keyword", "reason": "embeddings disabled"}

    try:
        semantic = near_top(retrieve_vector(question, limit * 3))
    except Exception as exc:
        logger.exception("Vector search failed; falling back to lexical retrieval")
        return lexical[:limit], {
            "mode": "keyword",
            "reason": "vector search failed: " + _describe_error(exc),
        }

    lexical_min = LEXICAL_MIN_SCORE if semantic else max(LEXICAL_MIN_SCORE, LEXICAL_ALONE_MIN_SCORE)
    lexical = [item for item in lexical if item["score"] >= lexical_min]

    fused = {}
    for ranking, weight in (
        (lexical, LEXICAL_WEIGHT),
        (semantic, SEMANTIC_WEIGHT),
    ):
        for rank, item in enumerate(ranking):
            key = (item["document_id"], item["chunk_index"])
            entry = fused.setdefault(
                key,
                {
                    "title": item["title"],
                    "content": item["content"],
                    "document_id": item["document_id"],
                    "chunk_index": item["chunk_index"],
                    "similarity": None,
                    "score": 0.0,
                },
            )
            entry["score"] += weight / (RRF_K + rank + 1)
            if item.get("similarity") is not None:
                entry["similarity"] = item["similarity"]

    ranked = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:limit]
    for entry in ranked:
        entry["score"] = round(entry["score"], 4)

    return ranked, {"mode": "hybrid", "reason": ""}


def retrieve(question, limit=4):
    return retrieve_ex(question, limit)[0]
