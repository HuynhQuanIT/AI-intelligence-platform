"""Hàm dùng chung cho test đăng nhập/phiên/hạn mức/nhóm."""
import re
import uuid

from app.core import passwords
from app.core.db import query
from app.services import mailer
from conftest import bearer, random_ip

PASSWORD = "Mat-khau-manh-123"
CSRF = {"X-Requested-With": "aip"}


def unique_email(prefix="u"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def ip_header():
    return {"X-Real-IP": random_ip()}


def new_client():
    """TestClient riêng (cookie riêng) cho từng thiết bị/người dùng."""
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def make_user(role="user", active=True, password=PASSWORD):
    """Tạo thẳng trong DB, đăng nhập bằng một client mới. Trả (email, headers, id, client)."""
    email, uid = unique_email(role), str(uuid.uuid4())
    query(
        "INSERT INTO users(id, email, password_hash, role, is_active, email_verified_at) "
        "VALUES (%s, %s, %s, %s, %s, NOW())",
        (uid, email, passwords.hash_password(password), role, active), False,
    )
    client = new_client()
    if not active:
        return email, None, uid, client
    r = client.post("/auth/login", json={"email": email, "password": password}, headers=ip_header())
    assert r.status_code == 200, r.text
    return email, bearer(r.json()["access_token"]), uid, client


def last_code(email):
    for mail in reversed(mailer.OUTBOX):
        if mail["to"] == email:
            found = re.search(r"\b(\d{6})\b", mail["body"])
            if found:
                return found.group(1)
    return None


def add_doc(admin_client, title, content):
    r = admin_client.post("/documents", json={"title": title, "content": content})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def add_success_logs(user_id, n):
    """Giả lập n tin nhắn thành công trong hôm nay để thử hạn mức mà không gọi model."""
    for _ in range(n):
        query(
            "INSERT INTO usage_logs(request_id, provider, model, input_tokens, output_tokens, cost_usd, "
            "latency_ms, status, user_id) VALUES (%s,'mock','m',1,1,0,1,'success',%s)",
            (str(uuid.uuid4()), user_id), False,
        )
