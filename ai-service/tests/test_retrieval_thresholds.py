"""
Số liệu lấy từ lần đo thật ngày 04/10/2026 (gemini-embedding-001, 768 chiều, hybrid).
Test này khóa ngưỡng: đổi MIN_TOP_SIMILARITY / MIN_SIMILARITY / SEMANTIC_MARGIN làm hỏng
một ca bên dưới nghĩa là phải đo lại trước khi chấp nhận thay đổi.
"""
import pytest

from app import rag


def hits(*sims):
    return [{"similarity": s, "title": "t", "content": "c", "document_id": "d", "chunk_index": i}
            for i, s in enumerate(sims)]


RELEVANT = [
    ("RAG la gi?", (0.744, 0.741, 0.716, 0.701)),
    ("Document chunking trong RAG là gì?", (0.847, 0.816, 0.788, 0.752)),
    ("Quy định thử nghiệm AI Platform nói gì?", (0.778, 0.732, 0.721, 0.693)),
    ("SSE và WebSocket khác nhau thế nào?", (0.727, 0.719, 0.713, 0.713)),
    ("Báo cáo kết quả hệ thống AI Platform năm 2026", (0.815, 0.803, 0.783, 0.713)),
    ("What is retrieval augmented generation?", (0.783, 0.782, 0.717, 0.708)),
]

IRRELEVANT = [
    ("Tính giúp tôi 12 * 34", (0.638, 0.604, 0.588, 0.584)),
    ("Hôm nay thời tiết thế nào?", (0.613, 0.603, 0.593, 0.586)),
    ("Giá vàng hôm nay là bao nhiêu?", (0.633, 0.568, 0.545, 0.541)),
    ("Công thức nấu phở bò", (0.636, 0.557, 0.553, 0.546)),
    ("Who won the 2018 World Cup?", (0.521, 0.477, 0.461, 0.461)),
    ("How do I bake bread?", (0.557, 0.519, 0.507, 0.505)),
]


@pytest.mark.parametrize("question,sims", RELEVANT, ids=[q for q, _ in RELEVANT])
def test_relevant_questions_keep_all_chunks(question, sims):
    assert len(rag.near_top(hits(*sims))) == len(sims)


@pytest.mark.parametrize("question,sims", IRRELEVANT, ids=[q for q, _ in IRRELEVANT])
def test_irrelevant_questions_return_nothing(question, sims):
    assert rag.near_top(hits(*sims)) == []


def test_empty_input():
    assert rag.near_top([]) == []


def test_weak_secondary_chunks_are_dropped():
    kept = rag.near_top(hits(0.85, 0.80, 0.62))
    assert [h["similarity"] for h in kept] == [0.85, 0.80]


def test_keywords_ignore_stopwords_and_short_numbers():
    assert "la" not in rag.keywords("RAG là gì?")
    assert "12" not in rag.keywords("Tính 12 * 34 giúp tôi")
    assert "rag" in rag.keywords("RAG là gì?")


def test_normalize_text_removes_diacritics_and_punctuation():
    assert rag.normalize_text("Bỏ qua, các HƯỚNG DẪN!") == "bo qua cac huong dan"