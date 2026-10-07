"""Tài liệu của Knowledge Center: dán, tải lên, xem, xóa, tải file gốc, reindex."""
import asyncio
import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from ..agents.security import scan_text
from ..rag import embeddings
from ..rag.documents import (
    DocumentTooLarge,
    DuplicateDocument,
    NoOriginalFile,
    add_document,
    add_uploaded_document,
    delete_document,
    documents,
    get_document,
    get_document_file,
    reindex_missing,
)
from ..rag.extract import ALLOWED_EXTENSIONS, ExtractError, extension, extract_text
from ..schemas import Doc

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


@router.post("/documents")
def create_doc(b: Doc):
    return add_document(
        title=b.title,
        content=b.content,
    )


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=250),
):
    filename = file.filename or ""
    ext = extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Chỉ hỗ trợ: " + ", ".join(sorted(ALLOWED_EXTENSIONS)),
        )

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File vượt quá 10 MB.")
    if not data:
        raise HTTPException(status_code=422, detail="File rỗng.")

    try:
        text = await asyncio.to_thread(extract_text, filename, data)
        result = await asyncio.to_thread(
            add_uploaded_document, filename, title, data, text
        )
    except ExtractError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DocumentTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except DuplicateDocument as exc:
        raise HTTPException(
            status_code=409,
            detail=f"File này đã được index (tài liệu '{exc.title}', id {exc.document_id}).",
        )
    except Exception:
        logger.exception("Document upload failed: %s", filename)
        raise HTTPException(
            status_code=503,
            detail="Không lưu được tài liệu (MinIO hoặc database lỗi). Xem log ai-service.",
        )

    # Không chặn việc lưu: lọc thật sự nằm ở Analysis Agent lúc truy xuất.
    result["security_matches"] = scan_text(text)
    return result


@router.get("/documents")
def get_docs():
    return documents()

def valid_document_id(value: str) -> str:
    """id không phải UUID thì coi như không tồn tại (tránh lỗi 500 từ cột uuid)."""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")


@router.get("/documents/{document_id}")
def get_doc_detail(document_id: str):
    document = get_document(valid_document_id(document_id))

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    return document

@router.delete("/documents/{document_id}")
def delete_doc(document_id: str):
    document_id = valid_document_id(document_id)
    if not delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}


@router.get("/documents/{document_id}/file")
def download_doc(document_id: str):
    document_id = valid_document_id(document_id)
    try:
        found = get_document_file(document_id)
    except NoOriginalFile:
        raise HTTPException(
            status_code=404,
            detail="Tài liệu này được dán trực tiếp, không có file gốc.",
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="File gốc không còn trong kho lưu trữ."
        )

    if found is None:
        raise HTTPException(status_code=404, detail="Document not found")

    filename, content_type, data = found
    encoded = quote(filename)
    ascii_name = filename.encode("ascii", "ignore").decode() or "document"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            # File do người dùng tải lên là dữ liệu không tin cậy: luôn tải về, không mở trực tiếp.
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}",
            "X-Content-Type-Options": "nosniff",
            "X-Document-Filename": encoded,
        },
    )


@router.post("/documents/reindex")
def reindex_documents():
    if not embeddings.enabled():
        raise HTTPException(
            status_code=400,
            detail="Embeddings are disabled: need LLM_PROVIDER=gemini and GEMINI_API_KEY.",
        )
    return reindex_missing()
