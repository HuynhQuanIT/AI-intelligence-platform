"""Quản lý cuộc trò chuyện."""
from fastapi import APIRouter, Depends, HTTPException

from ..services import conversations
from .deps import current_user

router = APIRouter(tags=["conversations"])


@router.post("/conversations")
def create_conversation(user: dict = Depends(current_user)):
    return conversations.create(user["id"])


@router.get("/conversations")
def list_conversations(user: dict = Depends(current_user)):
    return conversations.list_all(user["id"])


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, user: dict = Depends(current_user)):
    try:
        return conversations.messages(conversations.parse_id(conversation_id), user["id"])
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: dict = Depends(current_user)):
    try:
        cid = conversations.parse_id(conversation_id)
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversations.delete(cid, user["id"]):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": cid}
