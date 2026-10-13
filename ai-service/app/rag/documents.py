"""Vòng đời tài liệu: thêm (dán/tải lên), liệt kê, xem, xóa, tải file gốc, tạo embedding bổ sung."""
import hashlib
import logging
import re
import uuid

from ..core.db import query, transaction
from . import embeddings, storage
from .access import PUBLIC_ONLY, visible_sql
from .chunking import split_text
from .extract import extension

logger = logging.getLogger(__name__)


MAX_CHUNKS = 300  # ~270k ký tự; chặn tài liệu làm tốn quá nhiều lượt gọi embedding
CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
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
    # Dán trùng nội dung (bấm "Index" hai lần, request chậm...) không được tạo hai tài liệu giống nhau.
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = query(
        "SELECT id::text AS id, title FROM documents WHERE content_hash = %s AND owner_id IS NULL LIMIT 1", (digest,))
    if existing:
        raise DuplicateDocument(existing[0]["id"], existing[0]["title"])
    did = str(uuid.uuid4())
    chunks = split_text(content) or [content]
    vectors = _embed_chunks(title, chunks)
    _insert_document(did, title, title, chunks, vectors, {"content_hash": digest})
    return _result(did, title, title, chunks, vectors)


def ensure_schema() -> None:
    """Cột error cho tài liệu xử lý lỗi; và dọn các tài liệu kẹt 'processing' do lần chạy trước bị dừng."""
    with transaction() as cur:
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS error TEXT")
        # Chủ sở hữu: tài liệu người dùng tải lên từ khung chat. Xóa user thì xóa luôn tài liệu riêng của họ
        # (SET NULL sẽ vô tình biến chúng thành công khai).
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE")
        cur.execute("DROP INDEX IF EXISTS documents_content_hash_idx")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS documents_hash_owner_idx ON documents("
            "content_hash, COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::uuid)) "
            "WHERE content_hash IS NOT NULL")
    fail_stale(STARTUP_GRACE_SECONDS)


STARTUP_GRACE_SECONDS = 120   # lúc khởi động: tài liệu 'processing' quá 2 phút chắc chắn đã mất tiến trình xử lý
STALE_SECONDS = 15 * 60       # đang chạy: quá 15 phút coi như treo


def fail_stale(older_than_seconds: int = STALE_SECONDS) -> int:
    rows = query(
        "UPDATE documents SET status = 'failed', "
        "error = 'Quá trình xử lý bị gián đoạn (máy chủ khởi động lại hoặc quá thời gian). Hãy bấm Thử lại.' "
        "WHERE status = 'processing' AND created_at < NOW() - make_interval(secs => %s) RETURNING id",
        (older_than_seconds,),
    )
    return len(rows or [])


def _display_name(filename: str) -> str:
    return filename.replace("\\", "/").split("/")[-1][:255] or "document"


def start_upload(filename, title, data, owner_id=None):
    """Bước NHANH (chạy trong request): kiểm tra trùng, lưu file gốc, tạo dòng status='processing'.
    Việc nặng (trích văn bản, chunk, embedding) làm ở process_document, chạy nền."""
    digest = hashlib.sha256(data).hexdigest()
    # Trùng nội dung được xét trong cùng phạm vi chủ sở hữu: file riêng của A không làm B bị báo "đã tồn tại".
    existing = query(
        "SELECT id::text AS id, title FROM documents WHERE content_hash = %s AND owner_id IS NOT DISTINCT FROM %s LIMIT 1",
        (digest, owner_id),
    )
    if existing:
        raise DuplicateDocument(existing[0]["id"], existing[0]["title"])

    did = str(uuid.uuid4())
    display_name = _display_name(filename)
    safe_name = re.sub(r"[^\w.\-]+", "_", display_name)[:100]
    key = f"{did}/{safe_name}"
    ext = extension(display_name)
    title = (title or "").strip() or display_name.rsplit(".", 1)[0]

    storage.put_object(key, data, CONTENT_TYPES[ext])
    try:
        with transaction() as cur:
            cur.execute(
                "INSERT INTO documents(id,title,filename,object_key,content_type,size_bytes,content_hash,status,owner_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'processing',%s)",
                (did, title, display_name, key, CONTENT_TYPES[ext], len(data), digest, owner_id),
            )
    except Exception:
        storage.remove_object(key)
        raise
    return {"id": did, "title": title, "filename": display_name, "size_bytes": len(data), "status": "processing"}


def _mark_failed(did, message):
    query("UPDATE documents SET status = 'failed', error = %s WHERE id = %s", (message[:500], did), False)


def process_document(did):
    """Chạy nền: đọc file gốc, trích văn bản, chia chunk, embedding rồi ghi chunk + status='processed'.
    Mọi lỗi đều được ghi vào cột error (status='failed') để giao diện hiển thị; không ném ra ngoài."""
    from .extract import ExtractError, extract_text

    try:
        rows = query(
            "SELECT title, filename, object_key FROM documents WHERE id = %s AND status = 'processing'", (did,))
        if not rows:
            return  # bị xóa hoặc đã có tiến trình khác xử lý
        row = rows[0]
        data = storage.get_object(row["object_key"])
        text = extract_text(row["filename"], data)
        chunks = split_text(text)
        if len(chunks) > MAX_CHUNKS:
            raise DocumentTooLarge(
                f"Tài liệu có {len(chunks)} chunks, vượt giới hạn {MAX_CHUNKS}. Hãy tách nhỏ file.")
        vectors = _embed_chunks(row["title"], chunks)
        with transaction() as cur:
            cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (did,))
            cur.executemany(
                "INSERT INTO document_chunks(document_id,chunk_index,content,embedding) VALUES(%s,%s,%s,%s::vector)",
                [(did, i, c, embeddings.to_pgvector(v) if v else None)
                 for i, (c, v) in enumerate(zip(chunks, vectors))],
            )
            cur.execute("UPDATE documents SET status = 'processed', error = NULL WHERE id = %s", (did,))
    except (ExtractError, DocumentTooLarge) as exc:
        _mark_failed(did, str(exc))
    except Exception:
        logger.exception("Xử lý tài liệu %s thất bại", did)
        _mark_failed(did, "Không xử lý được tài liệu (lỗi hệ thống). Xem log ai-service rồi bấm Thử lại.")


def retry_document(did):
    """Chuyển tài liệu failed về processing để chạy lại. Trả False nếu không phải trạng thái failed/không có file."""
    rows = query(
        "UPDATE documents SET status = 'processing', error = NULL, created_at = NOW() "
        "WHERE id = %s AND status = 'failed' AND object_key IS NOT NULL RETURNING id", (did,))
    return bool(rows)


def documents(viewer=PUBLIC_ONLY):
    cond, params = visible_sql(viewer)
    return query(
        """
        SELECT
            d.id::text,
            d.title,
            d.filename,
            d.status,
            d.created_at,
            d.size_bytes,
            d.error,
            d.owner_id::text AS owner_id,
            (SELECT u.email FROM users u WHERE u.id = d.owner_id) AS owner_email,
            (d.object_key IS NOT NULL) AS has_file
        FROM documents d
        WHERE """ + cond + """
        ORDER BY d.created_at DESC
        """,
        params,
    )

def owner_of(document_id):
    """owner_id (str) của tài liệu, None nếu không có chủ hoặc không tồn tại."""
    rows = query("SELECT owner_id::text AS owner_id FROM documents WHERE id = %s", (document_id,))
    return rows[0]["owner_id"] if rows else None


def user_document_count(user_id):
    return query("SELECT COUNT(*)::int AS n FROM documents WHERE owner_id = %s", (user_id,))[0]["n"]


def attachment_chunks(document_id, limit_chars):
    """Các đoạn đầu của tài liệu theo thứ tự, tổng tối đa limit_chars. Trả (đoạn, tổng số đoạn)."""
    rows = query(
        "SELECT chunk_index, content FROM document_chunks WHERE document_id = %s ORDER BY chunk_index",
        (document_id,))
    kept, total = [], 0
    for r in rows:
        if kept and total + len(r["content"]) > limit_chars:
            break
        kept.append({"chunk_index": r["chunk_index"], "content": r["content"]})
        total += len(r["content"])
    return kept, len(rows)


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


def get_document_file(document_id, viewer=PUBLIC_ONLY):
    """Trả (filename, content_type, bytes) hoặc None nếu không có tài liệu (hoặc người xem không có quyền)."""
    cond, params = visible_sql(viewer)
    rows = query(
        "SELECT d.filename, d.content_type, d.object_key FROM documents d WHERE d.id = %s AND " + cond,
        (document_id, *params),
    )
    if not rows:
        return None

    row = rows[0]
    if not row["object_key"]:
        raise NoOriginalFile()

    data = storage.get_object(row["object_key"])
    return row["filename"], row["content_type"] or "application/octet-stream", data


def get_document(document_id, viewer=PUBLIC_ONLY):
    cond, params = visible_sql(viewer)
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
        WHERE d.id = %s AND """ + cond + """
        ORDER BY c.chunk_index
        """,
        (document_id, *params)
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
