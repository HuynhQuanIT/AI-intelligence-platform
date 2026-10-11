"""Access token ngắn hạn + refresh token xoay vòng trong cookie httpOnly, đổi mật khẩu."""
import time

import pytest

from app.core import settings
from app.core.db import query
from app.services import mailer, ratelimit
from auth_helpers import CSRF, PASSWORD, ip_header, make_user
from conftest import bearer

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_limits(client):
    ratelimit.reset()
    yield


def login(email, password=PASSWORD, client=None):
    from auth_helpers import new_client
    c = client or new_client()
    r = c.post("/auth/login", json={"email": email, "password": password}, headers=ip_header())
    return c, r


def test_login_sets_httponly_cookie_and_hides_refresh_token_from_body(client):
    email, _, _, _ = make_user()
    c, r = login(email)
    assert r.status_code == 200
    assert "refresh_token" not in r.json()
    cookie = r.headers["set-cookie"].lower()
    assert "aip_refresh=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/auth" in cookie  # COOKIE_PATH của môi trường test


def test_refresh_requires_csrf_header(client):
    email, _, _, c = make_user()
    assert c.post("/auth/refresh").status_code == 403
    assert c.post("/auth/refresh", headers=CSRF).status_code == 200


def test_refresh_issues_working_access_token_and_rotates_cookie(client):
    email, _, _, c = make_user()
    old = c.cookies.get("aip_refresh")
    r = c.post("/auth/refresh", headers=CSRF)
    assert r.status_code == 200
    assert c.cookies.get("aip_refresh") != old
    assert c.get("/auth/me", headers=bearer(r.json()["access_token"])).json()["email"] == email


def test_refresh_without_cookie_is_401(client):
    from auth_helpers import new_client
    r = new_client().post("/auth/refresh", headers=CSRF)
    assert r.status_code == 401


def test_reusing_a_rotated_token_revokes_the_whole_family(client):
    from auth_helpers import new_client
    email, _, _, c = make_user()
    stolen = c.cookies.get("aip_refresh")
    assert c.post("/auth/refresh", headers=CSRF).status_code == 200       # hợp lệ: xoay vòng
    query("UPDATE refresh_tokens SET used_at = NOW() - INTERVAL '1 minute' WHERE used_at IS NOT NULL", (), False)

    thief = new_client()
    thief.cookies.set("aip_refresh", stolen, path="/auth")
    assert thief.post("/auth/refresh", headers=CSRF).status_code == 401   # dùng lại token cũ
    assert c.post("/auth/refresh", headers=CSRF).status_code == 401       # token hợp lệ cũng bị thu hồi


def test_parallel_tabs_within_grace_window_are_allowed(client):
    from auth_helpers import new_client
    email, _, _, c = make_user()
    token = c.cookies.get("aip_refresh")
    assert c.post("/auth/refresh", headers=CSRF).status_code == 200
    tab2 = new_client()
    tab2.cookies.set("aip_refresh", token, path="/auth")
    assert tab2.post("/auth/refresh", headers=CSRF).status_code == 200    # ngay sau khi xoay: còn ân hạn


def test_logout_revokes_refresh_and_clears_cookie(client):
    email, _, _, c = make_user()
    token = c.cookies.get("aip_refresh")
    assert c.post("/auth/logout").status_code == 403                      # cần header CSRF
    r = c.post("/auth/logout", headers=CSRF)
    assert r.status_code == 200
    assert "aip_refresh=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
    from auth_helpers import new_client
    again = new_client()
    again.cookies.set("aip_refresh", token, path="/auth")
    assert again.post("/auth/refresh", headers=CSRF).status_code == 401


def test_expired_refresh_token_is_rejected(client):
    email, _, uid, c = make_user()
    query("UPDATE refresh_tokens SET expires_at = NOW() - INTERVAL '1 second' WHERE user_id = %s", (uid,), False)
    assert c.post("/auth/refresh", headers=CSRF).status_code == 401


def test_refresh_token_is_stored_hashed(client):
    email, _, uid, c = make_user()
    raw = c.cookies.get("aip_refresh")
    rows = query("SELECT token_hash FROM refresh_tokens WHERE user_id = %s", (uid,))
    assert rows and all(raw not in r["token_hash"] and len(r["token_hash"]) == 64 for r in rows)


def test_deactivated_user_cannot_refresh(client):
    email, _, uid, c = make_user()
    query("UPDATE users SET is_active = FALSE WHERE id = %s", (uid,), False)
    assert c.post("/auth/refresh", headers=CSRF).status_code == 401


def test_admin_deactivation_revokes_sessions(client):
    email, _, uid, c = make_user()
    assert client.post(f"/users/{uid}/deactivate").status_code == 200
    assert c.post("/auth/refresh", headers=CSRF).status_code == 401


def test_access_token_default_is_short(client):
    email, _, _, _ = make_user()
    _, r = login(email)
    assert r.json()["expires_in"] == settings.access_token_minutes() * 60 <= 15 * 60


# ------------------------------ đổi mật khẩu ------------------------------

NEW = "Mat-khau-moi-456"


def test_change_password_flow(client):
    email, h, uid, c = make_user()
    other_c, _ = login(email)                                              # thiết bị thứ hai
    r = c.post("/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": NEW})
    assert r.status_code == 200, r.text
    assert c.get("/auth/me", headers=bearer(r.json()["access_token"])).status_code == 200  # thiết bị này vẫn đăng nhập
    assert c.get("/auth/me", headers=h).status_code == 401                 # access token cũ chết
    assert other_c.post("/auth/refresh", headers=CSRF).status_code == 401  # thiết bị khác bị đăng xuất
    assert login(email, PASSWORD)[1].status_code == 401
    assert login(email, NEW)[1].status_code == 200
    assert any(m["to"] == email and "đổi" in m["subject"] for m in mailer.OUTBOX)


def test_change_password_rejects_wrong_current_weak_and_same(client):
    email, h, uid, c = make_user()
    assert c.post("/auth/password", headers=h, json={"current_password": "sai-mat-khau-1", "new_password": NEW}).status_code == 400
    assert c.post("/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": "ngan"}).status_code == 422
    assert c.post("/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": PASSWORD}).status_code == 422
    assert login(email, PASSWORD)[1].status_code == 200                    # mật khẩu không bị đổi


def test_wrong_current_password_counts_toward_lockout(client):
    email, h, uid, c = make_user()
    for _ in range(5):
        c.post("/auth/password", headers=h, json={"current_password": "sai-mat-khau-1", "new_password": NEW})
    r = c.post("/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": NEW})
    assert r.status_code == 429
    assert login(email, PASSWORD)[1].status_code == 429                    # đăng nhập cũng bị khóa


def test_change_password_requires_login(anon):
    assert anon.post("/auth/password", json={"current_password": "x", "new_password": "y"}).status_code == 401


def test_login_and_refresh_include_quota_for_the_ui(client):
    email, _, uid, c = make_user()
    r = c.post("/auth/refresh", headers=CSRF)
    assert {"limit", "used", "remaining", "resets_at"} <= set(r.json()["user"]["quota"])
    _, r = login(email)
    assert r.json()["user"]["quota"]["used"] == 0
