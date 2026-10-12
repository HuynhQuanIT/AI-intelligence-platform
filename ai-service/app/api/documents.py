"""Tài liệu của Knowledge Center: dán, tải lên, xem, xóa, tải file gốc, reindex."""
import asyncio
import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile

from ..agents.security import scan_text
from ..rag.access import viewer_of
from ..rag import embeddings
from ..rag.documents import (
    DocumentTooLarge,
    DuplicateDocument,
    NoOriginalFile,
    add_document,
    delete_document,
    documents,
    fail_stale,
    get_document,
    get_document_file,
    process_document,
    reindex_missing,
    retry_document,
    start_upload,
)
from ..rag.extract import ALLOWED_EXTENSIONS, ExtractError, extension, extract_text
from ..schemas import Doc, IdsBody
from ..services import groups
from .deps import current_user, require_admin

logger = logging.getLogger(__name__)
# Mọi người đã đăng nhập được xem/tải tài liệu; thêm, xóa, reindex chỉ dành cho admin.
router = APIRouter(tags=["documents"], dependencies=[Depends(current_user)])
admin_only = [Depends(require_admin)]


@router.post("/documents", dependencies=admin_only)
def create_doc(b: Doc):
    return add_document(
        title=b.title,
        content=b.content,
    )


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/documents/upload", dependencies=admin_only, status_code=202)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=250),
):
    """Nhận file rồi trả 202 ngay (status='processing'); trích văn bản/chunk/embedding chạy nền.
    Giao diện hỏi lại GET /documents cho tới khi status là processed hoặc failed."""
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
        result = await asyncio.to_thread(start_upload, filename, title, data)
    except DuplicateDocument as exc:
        raise HTTPException(
            status_code=409,
            detail=f"File này đã được index (tài liệu '{exc.title}', id {exc.document_id}).",
        )
    except Exception:
        logger.exception("Document upload failed: %s", filename)
        raise HTTPException(
            status_code=503,
            detail="Không lưu được tài liệu (kho lưu trữ hoặc database lỗi). Xem log ai-service.",
        )

    background.add_task(process_document, result["id"])  # hàm đồng bộ: Starlette chạy trong threadpool
    return result


@router.post("/documents/{document_id}/retry", dependencies=admin_only, status_code=202)
def retry_doc(document_id: str, background: BackgroundTasks):
    document_id = valid_document_id(document_id)
    if not retry_document(document_id):
        raise HTTPException(status_code=409, detail="Chỉ thử lại được tài liệu đang ở trạng thái failed.")
    background.add_task(process_document, document_id)
    return {"id": document_id, "status": "processing"}


@router.get("/documents")
def get_docs(user: dict = Depends(current_user)):
    if user["role"] == "admin":
        fail_stale()  # tài liệu treo quá lâu ở 'processing' thì chuyển failed để admin thử lại
    rows = documents(viewer_of(user))
    if user["role"] == "admin":
        # Admin thấy mọi nhóm của tài liệu.
        by_doc = groups.groups_of_documents([r["id"] for r in rows])
        rows = [{**r, "groups": by_doc.get(r["id"], [])} for r in rows]
    else:
        # Người dùng thường chỉ thấy nhãn: Công khai, hoặc tên các nhóm CỦA MÌNH chứa tài liệu.
        rows = groups.mark_documents_for(user, rows)
    return rows


@router.put("/documents/{document_id}/groups", dependencies=admin_only)
def set_doc_groups(document_id: str, b: IdsBody):
    try:
        return {"groups": groups.set_document_groups(valid_document_id(document_id), b.ids)}
    except groups.GroupError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

def valid_document_id(value: str) -> str:
    """id không phải UUID thì coi như không tồn tại (tránh lỗi 500 từ cột uuid)."""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")


@router.get("/documents/{document_id}")
def get_doc_detail(document_id: str, user: dict = Depends(current_user)):
    document = get_document(valid_document_id(document_id), viewer_of(user))

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    return document

@router.delete("/documents/{document_id}", dependencies=admin_only)
def delete_doc(document_id: str):
    document_id = valid_document_id(document_id)
    if not delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}


@router.get("/documents/{document_id}/file")
def download_doc(document_id: str, user: dict = Depends(current_user)):
    document_id = valid_document_id(document_id)
    try:
        found = get_document_file(document_id, viewer_of(user))
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


@router.post("/documents/reindex", dependencies=admin_only)
def reindex_documents():
    if not embeddings.enabled():
        raise HTTPException(
            status_code=400,
            detail="Embeddings are disabled: need LLM_PROVIDER=gemini and GEMINI_API_KEY.",
        )
    return reindex_missing()
