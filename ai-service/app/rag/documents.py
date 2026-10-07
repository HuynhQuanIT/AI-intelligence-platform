"""Vòng đời tài liệu: thêm (dán/tải lên), liệt kê, xem, xóa, tải file gốc, tạo embedding bổ sung."""
import hashlib
import logging
import re
import uuid

from ..core.db import query, transaction
from . import embeddings, storage
from .chunking import split_text
from .extract import extension

logger = logging.getLogger(__name__)


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
