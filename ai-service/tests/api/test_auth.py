"""Đăng ký/đăng nhập/quên mật khẩu/phân quyền: FastAPI + PostgreSQL thật, mail ghi vào bộ nhớ."""
import re
import time
import uuid

import jwt
import pytest

from app.core import passwords, settings, tokens
from app.core.db import query
from app.services import mailer, ratelimit
from conftest import ADMIN_EMAIL, bearer, random_ip

pytestmark = pytest.mark.integration

PASSWORD = "Mat-khau-manh-123"


@pytest.fixture(autouse=True)
def clean_limits():
    ratelimit.reset()
    yield


def unique_email(prefix="u"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def ip_header():
    return {"X-Real-IP": random_ip()}


def last_code(email):
    for mail in reversed(mailer.OUTBOX):
        if mail["to"] == email:
            found = re.search(r"\b(\d{6})\b", mail["body"])
            if found:
                return found.group(1)
    return None


def make_user(anon, role="user", active=True):
    """Tạo thẳng trong DB (nhanh), rồi đăng nhập qua API. Trả (email, headers, id)."""
    email, uid = unique_email(role), str(uuid.uuid4())
    query(
        "INSERT INTO users(id, email, password_hash, role, is_active, email_verified_at) "
        "VALUES (%s, %s, %s, %s, %s, NOW())",
        (uid, email, passwords.hash_password(PASSWORD), role, active), False,
    )
    if not active:
        return email, None, uid
    r = anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header())
    assert r.status_code == 200, r.text
    return email, bearer(r.json()["access_token"]), uid


def register(anon, email, password=PASSWORD):
    h = ip_header()
    assert anon.post("/auth/register/start", json={"email": email}, headers=h).status_code == 200
    code = last_code(email)
    v = anon.post("/auth/register/verify", json={"email": email, "code": code})
    assert v.status_code == 200, v.text
    return anon.post("/auth/register/complete",
                     json={"token": v.json()["registration_token"], "password": password})


# --------------------------- bắt buộc đăng nhập ---------------------------

@pytest.mark.parametrize("method,path", [
    ("get", "/documents"), ("get", "/conversations"), ("post", "/conversations"),
    ("get", "/metrics"), ("get", "/traces"), ("get", "/agents"), ("get", "/security/events"),
    ("get", "/users"), ("get", "/auth/me"), ("delete", f"/documents/{uuid.uuid4()}"),
])
def test_endpoints_require_login(anon, method, path):
    assert getattr(anon, method)(path).status_code == 401


def test_chat_requires_login(anon):
    assert anon.post("/chat", json={"message": "hi"}).status_code == 401
    assert anon.post("/chat/stream", json={"message": "hi"}).status_code == 401


def test_health_stays_public(anon):
    assert anon.get("/health").status_code == 200


@pytest.mark.parametrize("header", ["", "Bearer", "Bearer not-a-jwt", "Basic abc", "bearer  "])
def test_malformed_authorization_header(anon, header):
    assert anon.get("/auth/me", headers={"Authorization": header}).status_code == 401


def test_expired_and_foreign_tokens_are_rejected(anon):
    _, headers, uid = make_user(anon)
    now = int(time.time())
    expired = jwt.encode({"sub": uid, "typ": "access", "tv": 0, "iat": now - 100, "exp": now - 5},
                         settings.jwt_secret(), algorithm="HS256")
    assert anon.get("/auth/me", headers=bearer(expired)).status_code == 401
    foreign = jwt.encode({"sub": uid, "typ": "access", "tv": 0, "iat": now, "exp": now + 100},
                         "x" * 40, algorithm="HS256")
    assert anon.get("/auth/me", headers=bearer(foreign)).status_code == 401
    assert anon.get("/auth/me", headers=headers).status_code == 200


def test_reset_token_cannot_be_used_as_access_token(anon):
    _, _, uid = make_user(anon)
    email = query("SELECT email FROM users WHERE id = %s", (uid,))[0]["email"]
    token = tokens.create_flow_token("reset", email, 0)
    assert anon.get("/auth/me", headers=bearer(token)).status_code == 401


# ------------------------------- đăng ký -------------------------------

def test_register_flow_with_admin_approval(anon, client):
    email = unique_email("reg")
    done = register(anon, email)
    assert done.status_code == 200 and done.json()["active"] is False

    pending = anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header())
    assert pending.status_code == 403  # đúng mật khẩu nhưng chưa được duyệt

    user = next(u for u in client.get("/users").json() if u["email"] == email)
    assert user["is_active"] is False and user["role"] == "user"
    assert client.post(f"/users/{user['id']}/approve").json()["is_active"] is True

    ok = anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header())
    assert ok.status_code == 200
    me = anon.get("/auth/me", headers=bearer(ok.json()["access_token"])).json()
    assert me["email"] == email and me["role"] == "user"


def test_password_is_stored_hashed_never_plaintext(anon):
    email = unique_email("hash")
    register(anon, email)
    stored = query("SELECT password_hash FROM users WHERE email = %s", (email,))[0]["password_hash"]
    assert stored.startswith("scrypt$") and PASSWORD not in stored


def test_otp_is_stored_as_hmac_not_plaintext(anon):
    email = unique_email("otp")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    code = last_code(email)
    stored = query("SELECT otp_hmac FROM otp_codes WHERE email = %s", (email,))[0]["otp_hmac"]
    assert code not in stored and len(stored) == 64


def test_register_start_answers_the_same_for_existing_email(anon):
    existing, _, _ = make_user(anon)
    fresh = unique_email("fresh")

    a = anon.post("/auth/register/start", json={"email": existing}, headers=ip_header())
    b = anon.post("/auth/register/start", json={"email": fresh}, headers=ip_header())
    assert (a.status_code, a.json()) == (b.status_code, b.json())

    mail = next(m for m in reversed(mailer.OUTBOX) if m["to"] == existing)
    assert "đã có tài khoản" in mail["subject"] and last_code(existing) is None
    # Email đã tồn tại không thể lấy được registration token dù đoán mã.
    assert anon.post("/auth/register/verify", json={"email": existing, "code": "123456"}).status_code == 400


def test_wrong_otp_is_rejected_and_attempts_are_limited(anon):
    email = unique_email("att")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    code = last_code(email)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(5):
        assert anon.post("/auth/register/verify", json={"email": email, "code": wrong}).status_code == 400
    # Đã sai 5 lần: mã đúng cũng không còn dùng được.
    assert anon.post("/auth/register/verify", json={"email": email, "code": code}).status_code == 400


def test_otp_is_single_use(anon):
    email = unique_email("once")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    code = last_code(email)
    assert anon.post("/auth/register/verify", json={"email": email, "code": code}).status_code == 200
    assert anon.post("/auth/register/verify", json={"email": email, "code": code}).status_code == 400


def test_expired_otp_is_rejected(anon):
    email = unique_email("exp")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    code = last_code(email)
    query("UPDATE otp_codes SET expires_at = NOW() - INTERVAL '1 second' WHERE email = %s", (email,), False)
    assert anon.post("/auth/register/verify", json={"email": email, "code": code}).status_code == 400


def test_otp_resend_cooldown(anon):
    email = unique_email("cool")
    assert anon.post("/auth/register/start", json={"email": email}, headers=ip_header()).status_code == 200
    r = anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_otp_per_email_limit(anon):
    email = unique_email("lim")
    for _ in range(3):
        assert anon.post("/auth/register/start", json={"email": email}, headers=ip_header()).status_code == 200
        query("UPDATE otp_codes SET created_at = created_at - INTERVAL '2 minutes' WHERE email = %s",
              (email,), False)
    assert anon.post("/auth/register/start", json={"email": email}, headers=ip_header()).status_code == 429


def test_new_otp_invalidates_the_previous_one(anon):
    email = unique_email("new")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    first = last_code(email)
    query("UPDATE otp_codes SET created_at = created_at - INTERVAL '2 minutes' WHERE email = %s", (email,), False)
    mailer.OUTBOX.clear()
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    second = last_code(email)
    if first != second:
        assert anon.post("/auth/register/verify", json={"email": email, "code": first}).status_code == 400
    assert anon.post("/auth/register/verify", json={"email": email, "code": second}).status_code == 200


def test_weak_password_and_bad_email_are_rejected(anon):
    assert anon.post("/auth/register/start", json={"email": "khong-phai-email"}).status_code == 422
    email = unique_email("weak")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    v = anon.post("/auth/register/verify", json={"email": email, "code": last_code(email)})
    r = anon.post("/auth/register/complete", json={"token": v.json()["registration_token"], "password": "123456"})
    assert r.status_code == 422
    assert query("SELECT 1 FROM users WHERE email = %s", (email,)) == []


def test_registration_token_is_required_and_single_use(anon):
    assert anon.post("/auth/register/complete", json={"token": "abc", "password": PASSWORD}).status_code == 400
    email = unique_email("tok")
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    v = anon.post("/auth/register/verify", json={"email": email, "code": last_code(email)})
    token = v.json()["registration_token"]
    assert anon.post("/auth/register/complete", json={"token": token, "password": PASSWORD}).status_code == 200
    assert anon.post("/auth/register/complete", json={"token": token, "password": PASSWORD}).status_code == 409


def test_registration_modes(anon, monkeypatch):
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    assert anon.post("/auth/register/start", json={"email": unique_email()}, headers=ip_header()).status_code == 403

    monkeypatch.setenv("REGISTRATION_MODE", "domain")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "congty.vn")
    assert anon.post("/auth/register/start", json={"email": unique_email()}, headers=ip_header()).status_code == 403
    ok = f"{uuid.uuid4().hex[:8]}@congty.vn"
    assert register(anon, ok).json()["active"] is True  # email thuộc miền cho phép: dùng được ngay

    monkeypatch.setenv("REGISTRATION_MODE", "open")
    assert register(anon, unique_email("open")).json()["active"] is True


# ------------------------------- đăng nhập -------------------------------

def test_login_errors_do_not_reveal_whether_email_exists(anon):
    email, _, _ = make_user(anon)
    wrong_pw = anon.post("/auth/login", json={"email": email, "password": "Sai-mat-khau-1"}, headers=ip_header())
    unknown = anon.post("/auth/login", json={"email": unique_email("none"), "password": "Sai-mat-khau-1"},
                        headers=ip_header())
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_account_locks_after_five_failures_and_recovers(anon):
    email, _, uid = make_user(anon)
    for _ in range(5):
        r = anon.post("/auth/login", json={"email": email, "password": "Sai-mat-khau-1"}, headers=ip_header())
        assert r.status_code == 401
    locked = anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header())
    assert locked.status_code == 429 and "Retry-After" in locked.headers  # đúng mật khẩu vẫn bị khóa

    query("UPDATE users SET locked_until = NOW() - INTERVAL '1 second' WHERE id = %s", (uid,), False)
    assert anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header()).status_code == 200


def test_ip_is_throttled_after_many_failures(anon):
    ip = {"X-Real-IP": random_ip()}
    for _ in range(20):
        anon.post("/auth/login", json={"email": unique_email("x"), "password": "Sai-mat-khau-1"}, headers=ip)
    r = anon.post("/auth/login", json={"email": unique_email("x"), "password": "Sai-mat-khau-1"}, headers=ip)
    assert r.status_code == 429


def test_email_is_case_insensitive(anon):
    email, _, _ = make_user(anon)
    r = anon.post("/auth/login", json={"email": email.upper(), "password": PASSWORD}, headers=ip_header())
    assert r.status_code == 200


# ----------------------------- quên mật khẩu -----------------------------

def test_forgot_password_flow_revokes_old_sessions(anon):
    email, headers, _ = make_user(anon)
    assert anon.get("/auth/me", headers=headers).status_code == 200

    assert anon.post("/auth/forgot/start", json={"email": email}, headers=ip_header()).status_code == 200
    v = anon.post("/auth/forgot/verify", json={"email": email, "code": last_code(email)})
    assert v.status_code == 200
    token = v.json()["reset_token"]

    new_password = "Mat-khau-moi-456"
    assert anon.post("/auth/forgot/reset", json={"token": token, "password": new_password}).status_code == 200

    assert anon.get("/auth/me", headers=headers).status_code == 401           # phiên cũ hết hiệu lực
    assert anon.post("/auth/login", json={"email": email, "password": PASSWORD},
                     headers=ip_header()).status_code == 401                   # mật khẩu cũ
    assert anon.post("/auth/login", json={"email": email, "password": new_password},
                     headers=ip_header()).status_code == 200
    # Token đặt lại chỉ dùng một lần.
    assert anon.post("/auth/forgot/reset", json={"token": token, "password": "Mat-khau-khac-789"}).status_code == 400


def test_forgot_password_unknown_email_is_neutral_and_sends_nothing(anon):
    known, _, _ = make_user(anon)
    unknown = unique_email("ghost")
    before = len(mailer.OUTBOX)
    a = anon.post("/auth/forgot/start", json={"email": known}, headers=ip_header())
    b = anon.post("/auth/forgot/start", json={"email": unknown}, headers=ip_header())
    assert (a.status_code, a.json()) == (b.status_code, b.json())
    assert len(mailer.OUTBOX) == before + 1 and mailer.OUTBOX[-1]["to"] == known
    assert anon.post("/auth/forgot/verify", json={"email": unknown, "code": "123456"}).status_code == 400


def test_register_otp_cannot_reset_a_password(anon):
    email, _, _ = make_user(anon)
    anon.post("/auth/register/start", json={"email": email}, headers=ip_header())
    # OTP đăng ký (nếu có) không được chấp nhận ở luồng đặt lại mật khẩu.
    assert anon.post("/auth/forgot/verify", json={"email": email, "code": "123456"}).status_code == 400


# ------------------------------- phân quyền -------------------------------

def test_user_role_permissions(anon):
    _, user, _ = make_user(anon)
    assert anon.get("/documents", headers=user).status_code == 200          # xem Knowledge Center
    assert anon.post("/chat", json={"message": "Xin chào", "use_rag": False}, headers=user).status_code == 200

    forbidden = [
        ("post", "/documents", {"json": {"title": "t", "content": "c"}}),
        ("post", "/documents/upload", {"files": {"file": ("a.txt", b"hello", "text/plain")}}),
        ("delete", f"/documents/{uuid.uuid4()}", {}),
        ("post", "/documents/reindex", {}),
        ("get", "/metrics", {}), ("get", "/traces", {}), ("get", "/agents", {}),
        ("post", "/evaluate", {"json": {"question": "q", "answer": "a"}}),
        ("get", "/security/events", {}), ("post", "/security/scan", {"json": {"text": "x"}}),
        ("get", "/users", {}),
        ("post", f"/users/{uuid.uuid4()}/approve", {}),
        ("post", f"/users/{uuid.uuid4()}/role", {"json": {"role": "admin"}}),
    ]
    for method, path, kwargs in forbidden:
        r = getattr(anon, method)(path, headers=user, **kwargs)
        assert r.status_code == 403, (method, path, r.status_code)


def test_admin_can_use_admin_endpoints(client):
    assert client.get("/metrics").status_code == 200
    assert client.get("/users").status_code == 200


def test_conversations_are_private(anon):
    _, alice, _ = make_user(anon)
    _, bob, _ = make_user(anon)
    cid = anon.post("/conversations", headers=alice).json()["id"]
    anon.post("/chat", json={"message": "Bí mật của Alice", "use_rag": False, "conversation_id": cid},
              headers=alice)

    assert cid not in [c["id"] for c in anon.get("/conversations", headers=bob).json()]
    assert anon.get(f"/conversations/{cid}/messages", headers=bob).status_code == 404
    assert anon.delete(f"/conversations/{cid}", headers=bob).status_code == 404
    assert anon.post("/chat", json={"message": "x", "conversation_id": cid}, headers=bob).status_code == 404
    assert anon.post("/chat/stream", json={"message": "x", "conversation_id": cid}, headers=bob).status_code == 404
    # Bob không chen được tin nhắn nào vào hội thoại của Alice.
    assert len(anon.get(f"/conversations/{cid}/messages", headers=alice).json()) == 2
    assert anon.delete(f"/conversations/{cid}", headers=alice).status_code == 200


def test_even_admin_cannot_read_other_users_conversations(anon, client):
    _, alice, _ = make_user(anon)
    cid = anon.post("/conversations", headers=alice).json()["id"]
    assert client.get(f"/conversations/{cid}/messages").status_code == 404
    anon.delete(f"/conversations/{cid}", headers=alice)


def test_chat_usage_is_attributed_to_the_user(anon):
    _, user, uid = make_user(anon)
    rid = anon.post("/chat", json={"message": "Xin chào", "use_rag": False}, headers=user).json()["request_id"]
    assert query("SELECT user_id::text AS u FROM usage_logs WHERE request_id = %s", (rid,))[0]["u"] == uid


def test_chat_rate_limit_per_user(anon, monkeypatch):
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MIN", "2")
    _, limited, _ = make_user(anon)
    _, other, _ = make_user(anon)
    body = {"message": "Xin chào", "use_rag": False}
    assert anon.post("/chat", json=body, headers=limited).status_code == 200
    assert anon.post("/chat", json=body, headers=limited).status_code == 200
    r = anon.post("/chat", json=body, headers=limited)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert anon.post("/chat", json=body, headers=other).status_code == 200   # người khác không bị ảnh hưởng


# --------------------------- quản lý người dùng ---------------------------

def test_deactivating_a_user_revokes_the_session_immediately(anon, client):
    _, headers, uid = make_user(anon)
    assert anon.get("/auth/me", headers=headers).status_code == 200
    assert client.post(f"/users/{uid}/deactivate").json()["is_active"] is False
    assert anon.get("/auth/me", headers=headers).status_code == 401


def test_changing_role_takes_effect_and_revokes_old_token(anon, client):
    _, headers, uid = make_user(anon)
    assert anon.get("/metrics", headers=headers).status_code == 403
    assert client.post(f"/users/{uid}/role", json={"role": "admin"}).json()["role"] == "admin"
    assert anon.get("/metrics", headers=headers).status_code == 401   # token cũ mang role cũ: phải đăng nhập lại
    email = query("SELECT email FROM users WHERE id = %s", (uid,))[0]["email"]
    fresh = anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header()).json()
    assert anon.get("/metrics", headers=bearer(fresh["access_token"])).status_code == 200
    assert client.post(f"/users/{uid}/role", json={"role": "superuser"}).status_code == 422


def test_admin_cannot_lock_themselves_out(client):
    me = client.get("/auth/me").json()
    assert client.post(f"/users/{me['id']}/deactivate").status_code == 400
    assert client.post(f"/users/{me['id']}/role", json={"role": "user"}).status_code == 400
    assert client.post("/users/not-a-uuid/approve").status_code == 404


def test_admin_account_was_bootstrapped_from_env(client):
    me = client.get("/auth/me").json()
    assert me["email"] == ADMIN_EMAIL and me["role"] == "admin"


# ------------------------- admin xem chi tiết / đặt lại mật khẩu -------------------------

NEW_PASSWORD = "Mat-khau-moi-do-admin-1"


def test_admin_sees_user_detail_without_secrets(anon, client):
    email, headers, uid = make_user(anon)
    r = client.get(f"/users/{uid}")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email and body["role"] == "user" and body["is_active"] is True
    assert body["conversation_count"] == 0 and body["is_locked"] is False
    assert not ({"password_hash", "token_version"} & body.keys())
    assert client.get("/users/not-a-uuid").status_code == 404


def test_user_detail_counts_conversations_but_not_content(anon, client):
    _, headers, uid = make_user(anon)
    anon.post("/conversations", headers=headers)
    body = client.get(f"/users/{uid}").json()
    assert body["conversation_count"] == 1
    assert "messages" not in body and "title" not in body


def test_non_admin_cannot_see_detail_or_set_password(anon):
    _, user_headers, uid = make_user(anon)
    assert anon.get(f"/users/{uid}", headers=user_headers).status_code == 403
    assert anon.post(f"/users/{uid}/password", json={"password": NEW_PASSWORD}, headers=user_headers).status_code == 403
    assert anon.get(f"/users/{uid}").status_code == 401


def test_admin_sets_password_revokes_sessions_and_unlocks(anon, client):
    email, headers, uid = make_user(anon)
    query("UPDATE users SET failed_attempts = 5, locked_until = NOW() + INTERVAL '15 minutes' WHERE id = %s", (uid,), False)
    assert client.get(f"/users/{uid}").json()["is_locked"] is True

    mailer.OUTBOX.clear()
    r = client.post(f"/users/{uid}/password", json={"password": NEW_PASSWORD})
    assert r.status_code == 200, r.text

    assert anon.get("/auth/me", headers=headers).status_code == 401           # phiên cũ bị thu hồi
    assert client.get(f"/users/{uid}").json()["is_locked"] is False
    old = anon.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=ip_header())
    assert old.status_code == 401
    new = anon.post("/auth/login", json={"email": email, "password": NEW_PASSWORD}, headers=ip_header())
    assert new.status_code == 200
    # Mail thông báo không được chứa mật khẩu mới.
    sent = [m for m in mailer.OUTBOX if m["to"] == email]
    assert sent and all(NEW_PASSWORD not in m["body"] for m in sent)


def test_admin_set_password_enforces_policy_and_self_protection(anon, client):
    _, _, uid = make_user(anon)
    assert client.post(f"/users/{uid}/password", json={"password": "ngan"}).status_code == 422
    assert client.post(f"/users/{uid}/password", json={"password": "1234567890"}).status_code == 422
    me = client.get("/auth/me").json()
    assert client.post(f"/users/{me['id']}/password", json={"password": NEW_PASSWORD}).status_code == 400
    assert client.post("/users/not-a-uuid/password", json={"password": NEW_PASSWORD}).status_code == 404
