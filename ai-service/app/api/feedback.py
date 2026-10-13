"""Đánh giá câu trả lời (mọi người dùng) và thống kê (admin)."""
from fastapi import APIRouter, Depends, HTTPException

from ..schemas import Feedback
from ..services import feedback
from .deps import current_user, require_admin

router = APIRouter(tags=["feedback"])


@router.put("/messages/{message_id}/feedback")
def rate_message(message_id: int, b: Feedback, user: dict = Depends(current_user)):
    try:
        return feedback.set_feedback(message_id, str(user["id"]), b.rating, b.comment)
    except feedback.MessageNotFound:
        raise HTTPException(status_code=404, detail="Message not found")


@router.get("/feedback/summary")
def feedback_summary(_: dict = Depends(require_admin)):
    return feedback.summary()
