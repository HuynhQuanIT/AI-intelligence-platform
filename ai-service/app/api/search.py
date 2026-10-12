"""Tìm kiếm tài liệu (từ khóa / ngữ nghĩa / kết hợp). Mọi người đã đăng nhập dùng được, kết quả chỉ gồm
tài liệu người đó được xem."""
import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core import settings
from ..rag.access import viewer_of
from ..services import ratelimit, search as search_service
from .deps import current_user

router = APIRouter(tags=["search"])


@router.get("/search")
async def search_documents(
    q: str = Query(..., min_length=2, max_length=300),
    mode: str = Query("hybrid"),
    limit: int = Query(10, ge=1, le=30),
    group_id: str | None = Query(None),
    user: dict = Depends(current_user),
):
    if mode not in search_service.MODES:
        raise HTTPException(status_code=422, detail="mode phải là hybrid, keyword hoặc semantic.")
    if group_id:
        try:
            group_id = str(uuid.UUID(group_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="Không tìm thấy nhóm.")
    if not q.strip() or len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="Từ khóa quá ngắn.")

    # Tìm ngữ nghĩa tốn một lượt gọi embedding cho mỗi câu truy vấn nên có giới hạn riêng.
    wait = ratelimit.hit(f"search:{user['id']}", settings.chat_rate_per_minute() * 3, 60)
    if wait:
        raise HTTPException(status_code=429, detail=f"Bạn tìm quá nhanh. Hãy thử lại sau {wait} giây.",
                            headers={"Retry-After": str(wait)})

    return await asyncio.to_thread(search_service.search, q.strip(), mode, limit, viewer_of(user), group_id)
