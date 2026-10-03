import re
import uuid
import unicodedata

from .db import query, transaction


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


def add_document(title, content):
    did = str(uuid.uuid4())

    chunks = [
        content[i:i + 900]
        for i in range(0, len(content), 750)
    ] or [content]

    with transaction() as cur:
        cur.execute(
            "INSERT INTO documents(id,title,filename) VALUES(%s,%s,%s)",
            (did, title, title),
        )
        cur.executemany(
            "INSERT INTO document_chunks(document_id,chunk_index,content) "
            "VALUES(%s,%s,%s)",
            [(did, i, chunk) for i, chunk in enumerate(chunks)],
        )

    return {
        "id": did,
        "title": title,
        "chunks": len(chunks),
        "status": "processed",
    }


def retrieve(question, limit=4):
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
    question_words = words(question)

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