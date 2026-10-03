import logging
import os
import re
import unicodedata
import uuid

from . import embeddings
from .db import query, transaction

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """
    Chuẩn hóa chữ thường, bỏ dấu tiếng Việt và loại ký tự đặc biệt.
    Ví dụ:
    'Quy định thử nghiệm' -> 'quy dinh thu nghiem'
    """
    text = (text or "").lower().strip()

    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    text = text.replace("đ", "d")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def words(text: str) -> set[str]:
    return set(re.findall(r"\w+", normalize_text(text)))


# Từ chức năng (đã chuẩn hóa, không dấu). Nếu không loại bỏ, câu hỏi như
# "How often is the company car serviced?" khớp từ khóa với gần như mọi chunk
# qua "is", "the", "how"... và đẩy chunk đúng nghĩa ra khỏi top kết quả.
STOPWORDS = {
    # English
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am",
    "do", "does", "did", "how", "what", "when", "where", "which", "who",
    "whom", "why", "of", "to", "in", "on", "at", "for", "from", "by",
    "with", "and", "or", "not", "it", "its", "this", "that", "these",
    "those", "i", "you", "we", "they", "he", "she", "my", "your", "our",
    "their", "can", "could", "should", "would", "will", "may", "might",
    "about", "as", "if", "so", "than", "then", "there", "has", "have", "had",
    # Vietnamese (không dấu)
    "la", "gi", "va", "cua", "co", "cho", "cac", "nhung", "mot", "nay",
    "duoc", "trong", "khi", "de", "voi", "thi", "ma", "hay", "nhu", "nao",
    "khong", "bi", "o", "tai", "ve", "tu", "den", "da", "se", "dang",
    "rat", "cung", "nhe", "ban", "toi", "minh",
}


def keywords(text: str) -> set[str]:
    """Từ khóa có nghĩa của câu hỏi; nếu toàn từ chức năng thì dùng lại tất cả."""
    all_words = words(text)
    return (all_words - STOPWORDS) or all_words


def add_document(title, content):
    did = str(uuid.uuid4())

    chunks = [
        content[i:i + 900]
        for i in range(0, len(content), 750)
    ] or [content]

    # Tạo embedding TRƯỚC khi mở transaction để không giữ kết nối DB lúc chờ API.
    # Lỗi embedding không làm mất tài liệu: lưu không vector, backfill sau.
    vectors = [None] * len(chunks)
    if embeddings.enabled():
        try:
            vectors = embeddings.embed_texts(
                [f"{title}\n\n{chunk}" for chunk in chunks],
                "RETRIEVAL_DOCUMENT",
            )
        except Exception:
            logger.exception("Embedding failed; document saved without vectors")

    with transaction() as cur:
        cur.execute(
            "INSERT INTO documents(id,title,filename) VALUES(%s,%s,%s)",
            (did, title, title),
        )
        cur.executemany(
            "INSERT INTO document_chunks(document_id,chunk_index,content,embedding) "
            "VALUES(%s,%s,%s,%s::vector)",
            [
                (did, i, chunk, embeddings.to_pgvector(v) if v else None)
                for i, (chunk, v) in enumerate(zip(chunks, vectors))
            ],
        )

    return {
        "id": did,
        "title": title,
        "chunks": len(chunks),
        "embedded": all(v is not None for v in vectors),
        "status": "processed",
    }


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


def documents():
    return query(
        """
        SELECT
            id::text,
            title,
            filename,
            status,
            created_at
        FROM documents
        ORDER BY created_at DESC
        """
    )

def get_document(document_id):
    rows = query(
        """
        SELECT
            d.id::text AS id,
            d.title,
            d.filename,
            d.status,
            d.created_at,
            c.chunk_index,
            c.content
        FROM documents d
        LEFT JOIN document_chunks c
            ON c.document_id = d.id
        WHERE d.id = %s
        ORDER BY c.chunk_index
        """,
        (document_id,)
    )

    if not rows:
        return None

    first = rows[0]

    return {
        "id": first["id"],
        "title": first["title"],
        "filename": first["filename"],
        "status": first["status"],
        "created_at": first["created_at"].isoformat()
            if first["created_at"] else None,
        "chunks": [
            {
                "chunk_index": row["chunk_index"],
                "content": row["content"],
            }
            for row in rows
            if row["chunk_index"] is not None
        ],
    }

RRF_K = 60
# Vector là tín hiệu chính, từ khóa chỉ hỗ trợ (trọng số thấp hơn).
SEMANTIC_WEIGHT = float(os.getenv("RRF_SEMANTIC_WEIGHT", "1.0"))
LEXICAL_WEIGHT = float(os.getenv("RRF_LEXICAL_WEIGHT", "0.5"))
# Chỉ giữ kết quả vector có độ giống cách kết quả tốt nhất không quá ngần này.
# Dùng ngưỡng tương đối vì độ giống tuyệt đối thay đổi theo model và ngôn ngữ.
SEMANTIC_MARGIN = float(os.getenv("SEMANTIC_MARGIN", "0.10"))


def retrieve_vector(question, limit):
    vec = embeddings.to_pgvector(
        embeddings.embed_texts([question], "RETRIEVAL_QUERY")[0]
    )

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
    """Bỏ các kết quả vector kém xa kết quả tốt nhất (danh sách đã sắp giảm dần)."""
    if not semantic:
        return semantic
    cutoff = semantic[0]["similarity"] - SEMANTIC_MARGIN
    return [item for item in semantic if item["similarity"] >= cutoff]


def retrieve(question, limit=4):
    """Hybrid: từ khóa + vector, gộp bằng Reciprocal Rank Fusion có trọng số."""
    lexical = retrieve_lexical(question, limit * 3)

    if not embeddings.enabled():
        return lexical[:limit]

    try:
        semantic = near_top(retrieve_vector(question, limit * 3))
    except Exception:
        logger.exception("Vector search failed; falling back to lexical retrieval")
        return lexical[:limit]

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

    return ranked


def reindex_missing(batch_size=20):
    """Tạo embedding cho các chunk chưa có (tài liệu cũ hoặc lần embed bị lỗi)."""
    rows = query(
        """
        SELECT c.id, d.title, c.content
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NULL
        ORDER BY c.id
        """
    )

    done = 0
    for i in range(0, len(rows), batch_size):
        part = rows[i:i + batch_size]
        vectors = embeddings.embed_texts(
            [f"{r['title']}\n\n{r['content']}" for r in part],
            "RETRIEVAL_DOCUMENT",
        )
        with transaction() as cur:
            cur.executemany(
                "UPDATE document_chunks SET embedding = %s::vector WHERE id = %s",
                [(embeddings.to_pgvector(v), r["id"]) for v, r in zip(vectors, part)],
            )
        done += len(part)

    return {"embedded": done}