"""Quản lý cuộc trò chuyện."""
from fastapi import APIRouter, HTTPException

from ..services import conversations

router = APIRouter(tags=["conversations"])


@router.post("/conversations")
def create_conversation():
    return conversations.create()


@router.get("/conversations")
def list_conversations():
    return conversations.list_all()


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str):
    try:
        return conversations.messages(conversations.parse_id(conversation_id))
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    try:
        cid = conversations.parse_id(conversation_id)
    except conversations.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversations.delete(cid):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": cid}
