import hashlib
import logging
import os
import re
import unicodedata
import uuid

from . import embeddings, storage
from .chunking import split_text
from .db import query, transaction
from .extract import extension

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


MAX_CHUNKS = 300  # ~270k ký tự; chặn tài liệu làm tốn quá nhiều lượt gọi embedding
CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class DuplicateDocument(Exception):
    def __init__(self, document_id, title):
        super().__init__(f"Document already indexed: {title}")
        self.document_id = document_id
        self.title = title


class DocumentTooLarge(ValueError):
    pass


class NoOriginalFile(Exception):
    """Tài liệu được dán trực tiếp, không có file gốc."""


def _embed_chunks(title, chunks):
    """Tạo embedding TRƯỚC khi mở transaction để không giữ kết nối DB lúc chờ API.
    Lỗi embedding không làm mất tài liệu: lưu không vector, backfill sau."""
    vectors = [None] * len(chunks)
    if embeddings.enabled():
        try:
            vectors = embeddings.embed_texts(
                [f"{title}\n\n{chunk}" for chunk in chunks],
                "RETRIEVAL_DOCUMENT",
            )
        except Exception:
            logger.exception("Embedding failed; document saved without vectors")
    return vectors


def _insert_document(did, title, filename, chunks, vectors, file_info=None):
    info = file_info or {}
    with transaction() as cur:
        cur.execute(
            "INSERT INTO documents(id,title,filename,object_key,content_type,size_bytes,content_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                did, title, filename,
                info.get("object_key"), info.get("content_type"),
                info.get("size_bytes"), info.get("content_hash"),
            ),
        )
        cur.executemany(
            "INSERT INTO document_chunks(document_id,chunk_index,content,embedding) "
            "VALUES(%s,%s,%s,%s::vector)",
            [
                (did, i, chunk, embeddings.to_pgvector(v) if v else None)
                for i, (chunk, v) in enumerate(zip(chunks, vectors))
            ],
        )


def _result(did, title, filename, chunks, vectors, size_bytes=None):
    return {
        "id": did,
        "title": title,
        "filename": filename,
        "chunks": len(chunks),
        "embedded": all(v is not None for v in vectors),
        "size_bytes": size_bytes,
        "status": "processed",
    }


def add_document(title, content):
    did = str(uuid.uuid4())
    chunks = split_text(content) or [content]
    vectors = _embed_chunks(title, chunks)
    _insert_document(did, title, title, chunks, vectors)
    return _result(did, title, title, chunks, vectors)


def add_uploaded_document(filename, title, data, text):
    """Lưu file gốc vào MinIO, chia chunk, embed rồi ghi DB (đồng bộ, gọi trong thread)."""
    digest = hashlib.sha256(data).hexdigest()
    existing = query(
        "SELECT id::text AS id, title FROM documents WHERE content_hash = %s LIMIT 1",
        (digest,),
    )
    if existing:
        raise DuplicateDocument(existing[0]["id"], existing[0]["title"])

    chunks = split_text(text)
    if len(chunks) > MAX_CHUNKS:
        raise DocumentTooLarge(
            f"Tài liệu có {len(chunks)} chunks, vượt giới hạn {MAX_CHUNKS}. Hãy tách nhỏ file."
        )

    did = str(uuid.uuid4())
    display_name = filename.replace("\\", "/").split("/")[-1][:255] or "document"
    safe_name = re.sub(r"[^\w.\-]+", "_", display_name)[:100]
    key = f"{did}/{safe_name}"
    ext = extension(display_name)
    title = (title or "").strip() or display_name.rsplit(".", 1)[0]

    vectors = _embed_chunks(title, chunks)

    storage.put_object(key, data, CONTENT_TYPES[ext])
    try:
        _insert_document(
            did, title, display_name, chunks, vectors,
            {
                "object_key": key,
                "content_type": CONTENT_TYPES[ext],
                "size_bytes": len(data),
                "content_hash": digest,
            },
        )
    except Exception:
        storage.remove_object(key)
        raise

    return _result(did, title, display_name, chunks, vectors, len(data))


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
            created_at,
            size_bytes,
            (object_key IS NOT NULL) AS has_file
        FROM documents
        ORDER BY created_at DESC
        """
    )

def delete_document(document_id):
    """Xóa dòng DB (chunk xóa theo cascade) rồi xóa file gốc. False nếu không tồn tại."""
    with transaction() as cur:
        cur.execute(
            "DELETE FROM documents WHERE id = %s RETURNING object_key",
            (document_id,),
        )
        row = cur.fetchone()

    if row is None:
        return False

    # Xóa DB trước: nếu xóa file lỗi thì chỉ còn file mồ côi vô hại,
    # còn ngược lại sẽ để lại tài liệu trỏ tới file không tồn tại.
    if row["object_key"]:
        storage.remove_object(row["object_key"])
    return True


def get_document_file(document_id):
    """Trả (filename, content_type, bytes) hoặc None nếu không có tài liệu."""
    rows = query(
        "SELECT filename, content_type, object_key FROM documents WHERE id = %s",
        (document_id,),
    )
    if not rows:
        return None

    row = rows[0]
    if not row["object_key"]:
        raise NoOriginalFile()

    data = storage.get_object(row["object_key"])
    return row["filename"], row["content_type"] or "application/octet-stream", data


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
# Ngưỡng tuyệt đối: đo thực tế với gemini-embedding-001 (768 chiều) cho thấy chunk liên quan
# đạt ~0.67-0.74 còn chunk không liên quan ~0.50-0.54. Dưới ngưỡng thì không đưa vào ngữ cảnh.
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.60"))
# Khi chạy hybrid, kết quả chỉ khớp từ khóa phải khớp ít nhất ngần này tỉ lệ từ khóa của câu hỏi.
LEXICAL_MIN_SCORE = float(os.getenv("LEXICAL_MIN_SCORE", "0.5"))


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
    """Bỏ kết quả vector dưới ngưỡng tuyệt đối, rồi bỏ những kết quả kém xa kết quả tốt nhất
    (danh sách đã sắp giảm dần)."""
    semantic = [item for item in semantic if item["similarity"] >= MIN_SIMILARITY]
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

    lexical = [item for item in lexical if item["score"] >= LEXICAL_MIN_SCORE]

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