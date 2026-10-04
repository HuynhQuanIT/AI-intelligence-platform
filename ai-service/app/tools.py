"""
Công cụ mà agent được phép gọi. Tất cả đều CHỈ ĐỌC, có giới hạn đầu vào/đầu ra.
Việc bật/tắt từng công cụ nằm ở bảng agent_tools (đọc lại mỗi request).
"""
import ast
import logging
import operator
import uuid

from . import rag
from .db import query

logger = logging.getLogger(__name__)

MAX_TEXT = 700          # ký tự mỗi đoạn văn bản trả về cho model
MAX_LIST = 20           # số tài liệu tối đa khi liệt kê
MAX_SEARCH = 6          # số đoạn tối đa mỗi lần tìm
MAX_READ_CHUNKS = 5     # số chunk tối đa mỗi lần đọc


class ToolError(Exception):
    """Lỗi do đầu vào sai; thông điệp được trả lại cho model để nó tự sửa."""


def _int(args, key, default, low, high):
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise ToolError(f"'{key}' phải là số nguyên.")
    return max(low, min(high, int(value)))


def _text(args, key, max_len):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"Thiếu tham số '{key}' (chuỗi không rỗng).")
    return value.strip()[:max_len]


# --------------------------- các công cụ ---------------------------

def list_documents(args):
    limit = _int(args, "limit", 10, 1, MAX_LIST)
    all_rows = rag.documents()
    rows = all_rows[:limit]
    return {
        "total": len(all_rows),
        "returned": len(rows),
        "truncated": len(all_rows) > len(rows),
        "documents": [
            {
                "document_id": r["id"],
                "title": r["title"],
                "filename": r["filename"],
                # Tài liệu dán trực tiếp không có file gốc nên không có dung lượng (null, KHÔNG phải 0).
                "source": "uploaded_file" if r.get("has_file") else "pasted_text",
                "size_kb": round(r["size_bytes"] / 1024, 1) if r.get("size_bytes") else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


def search_documents(args):
    text = _text(args, "query", 300)
    limit = _int(args, "limit", 4, 1, MAX_SEARCH)
    hits = rag.retrieve(text, limit)
    return {
        "count": len(hits),
        "results": [
            {
                "title": h["title"],
                "document_id": h["document_id"],
                "chunk_index": h["chunk_index"],
                "similarity": h.get("similarity"),
                "text": h["content"][:MAX_TEXT],
            }
            for h in hits
        ],
    }


def read_document(args):
    raw_id = _text(args, "document_id", 64)
    try:
        document_id = str(uuid.UUID(raw_id))
    except ValueError:
        raise ToolError("'document_id' không phải UUID hợp lệ; lấy id từ list_documents hoặc search_documents.")

    start = _int(args, "start_chunk", 0, 0, 100000)
    count = _int(args, "count", 3, 1, MAX_READ_CHUNKS)

    document = rag.get_document(document_id)
    if document is None:
        raise ToolError("Không có tài liệu với id này.")

    chunks = document["chunks"]
    part = chunks[start:start + count]
    return {
        "title": document["title"],
        "total_chunks": len(chunks),
        "returned": [
            {"chunk_index": c["chunk_index"], "text": c["content"][:MAX_TEXT * 2]}
            for c in part
        ],
    }


_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}


def _eval(node, depth=0):
    if depth > 20:
        raise ToolError("Biểu thức quá phức tạp.")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand, depth + 1)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _eval(node.left, depth + 1)
        right = _eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 1_000_000):
            raise ToolError("Phép lũy thừa quá lớn.")
        try:
            return _BINARY[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ToolError("Chia cho 0.")
    raise ToolError("Chỉ hỗ trợ số và các phép + - * / // % ** cùng dấu ngoặc.")


def calculate(args):
    expression = _text(args, "expression", 10_000)
    if len(expression) > 200:
        raise ToolError("Biểu thức quá dài (tối đa 200 ký tự).")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ToolError("Biểu thức không hợp lệ.")
    value = _eval(tree)
    if isinstance(value, float):
        value = round(value, 10)
    elif abs(value) > 10**15:
        value = str(value)  # tránh mất độ chính xác khi chuyển sang JSON
    return {"expression": expression, "result": value}


# --------------------------- đăng ký ---------------------------

# parameters: {tên: (kiểu, mô tả, bắt buộc)}; kiểu: "string" | "integer"
TOOLS = {
    "list_documents": {
        "description": "Liệt kê các tài liệu đã được index (tiêu đề, tên file, nguồn, dung lượng nếu có, ngày tạo, document_id) và tổng số tài liệu. size_kb là null với tài liệu dán trực tiếp.",
        "parameters": {"limit": ("integer", f"Số tài liệu tối đa, 1-{MAX_LIST}. Mặc định 10.", False)},
        "run": list_documents,
    },
    "search_documents": {
        "description": "Tìm các đoạn tài liệu liên quan đến một truy vấn (tìm theo nghĩa + từ khóa). Dùng khi ngữ cảnh đã cung cấp chưa đủ.",
        "parameters": {
            "query": ("string", "Truy vấn tìm kiếm, nên viết lại cho cụ thể.", True),
            "limit": ("integer", f"Số đoạn tối đa, 1-{MAX_SEARCH}. Mặc định 4.", False),
        },
        "run": search_documents,
    },
    "read_document": {
        "description": "Đọc các chunk liên tiếp của một tài liệu theo document_id (lấy từ list_documents hoặc search_documents).",
        "parameters": {
            "document_id": ("string", "UUID của tài liệu.", True),
            "start_chunk": ("integer", "Chunk bắt đầu, từ 0. Mặc định 0.", False),
            "count": ("integer", f"Số chunk, 1-{MAX_READ_CHUNKS}. Mặc định 3.", False),
        },
        "run": read_document,
    },
    "calculate": {
        "description": "Tính một biểu thức số học (+ - * / // % ** và ngoặc). Dùng cho mọi phép tính thay vì tự nhẩm.",
        "parameters": {"expression": ("string", "Biểu thức, ví dụ (36.2 - 34.1) / 34.1 * 100.", True)},
        "run": calculate,
    },
}


def load_enabled_tools() -> list[str]:
    """Đọc công cụ đang bật. Lỗi DB -> không công cụ nào (an toàn theo mặc định)."""
    try:
        rows = query("SELECT name FROM agent_tools WHERE enabled")
        return [r["name"] for r in rows if r["name"] in TOOLS]
    except Exception:
        logger.exception("Cannot read agent_tools; running without tools")
        return []


def specs(names):
    return [
        {
            "name": name,
            "description": TOOLS[name]["description"],
            "parameters": TOOLS[name]["parameters"],
        }
        for name in names
        if name in TOOLS
    ]


def run_tool(name: str, args: dict) -> dict:
    """Đồng bộ (gọi trong thread). Ném ToolError nếu đầu vào sai."""
    if name not in TOOLS:
        raise ToolError(f"Công cụ '{name}' không tồn tại.")
    if not isinstance(args, dict):
        raise ToolError("Tham số phải là một object.")
    return TOOLS[name]["run"](args)