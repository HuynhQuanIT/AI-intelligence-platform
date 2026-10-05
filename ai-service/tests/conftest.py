import json
import os
import tempfile

# Phải đặt trước khi import app: storage đọc UPLOAD_DIR lúc import.
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["GEMINI_API_KEY"] = ""
os.environ["STORAGE_BACKEND"] = "local"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="uploads-test-")

import pytest


def pytest_collection_modifyitems(config, items):
    """Test đánh dấu integration tự bỏ qua khi không có PostgreSQL (chạy local không cần DB)."""
    if _db_available():
        return
    if os.getenv("REQUIRE_DB") == "1":
        raise pytest.UsageError("REQUIRE_DB=1 nhưng không kết nối được PostgreSQL (DATABASE_URL).")
    skip = pytest.mark.skip(reason="PostgreSQL không kết nối được (đặt DATABASE_URL)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _db_available() -> bool:
    try:
        import psycopg

        url = os.getenv(
            "DATABASE_URL",
            "postgresql://platform:platform_dev_password@localhost:5432/aiplatform",
        )
        with psycopg.connect(url, connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def parse_sse(text: str):
    """Chuyển chuỗi SSE thành danh sách (tên_sự_kiện, dữ_liệu)."""
    events = []
    for block in text.strip().split("\n\n"):
        head, data = block.split("\n", 1)
        events.append((head[len("event: "):], json.loads(data[len("data: "):])))
    return events


@pytest.fixture
def stream_chat(client):
    def run(payload):
        with client.stream("POST", "/chat/stream", json=payload) as response:
            body = "".join(response.iter_text())
            return response.status_code, response.headers, body

    return run