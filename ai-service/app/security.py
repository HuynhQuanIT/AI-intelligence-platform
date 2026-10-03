from .rag import normalize_text

# Viết ở dạng đã chuẩn hóa: chữ thường, không dấu, không dấu câu
PATTERNS = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore the above instructions",
    "disregard your instructions",
    "reveal system prompt",
    "reveal your system prompt",
    "print api key",
    "bypass security",
    "bo qua cac huong dan truoc",
    "bo qua moi huong dan",
    "tiet lo system prompt",
    "in ra api key",
]


def scan_text(text: str) -> list[str]:
    """Trả về danh sách mẫu tấn công khớp trong text (rỗng nếu an toàn)."""
    normalized = normalize_text(text)
    return [p for p in PATTERNS if p in normalized]