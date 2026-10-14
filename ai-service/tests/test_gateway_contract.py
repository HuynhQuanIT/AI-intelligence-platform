"""Gateway C# là proxy định kiểu: field nào của schemas.Chat không có trong ChatRequest.cs sẽ bị âm thầm bỏ."""
import re
from pathlib import Path

from app.schemas import Chat

CS = Path(__file__).resolve().parents[2] / "backend" / "AIPlatform.Api" / "Models" / "ChatRequest.cs"


def test_gateway_chat_request_forwards_every_chat_field():
    if not CS.exists():
        return
    src = CS.read_text(encoding="utf-8")
    cls = src.split("class ChatRequest", 1)[1].split("class HistoryItem", 1)[0]
    names = set(re.findall(r'JsonPropertyName\("([^"]+)"\)', cls))
    missing = set(Chat.model_fields) - names
    assert not missing, f"ChatRequest.cs thiếu field: {sorted(missing)}"
