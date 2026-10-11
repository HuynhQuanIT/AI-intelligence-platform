"""Người dùng, đăng ký/quên mật khẩu bằng OTP email, đăng nhập và phiên JWT.

Lỗi nghiệp vụ là AuthError(status, message) để lớp api đổi thành HTTP.
Trạng thái khóa tài khoản và OTP nằm trong database nên không mất khi khởi động lại.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..core import passwords, settings, tokens
from ..core.db import query, transaction
from . import groups, ratelimit

logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_COOLDOWN_SECONDS = 60
OTP_MAX_PER_WINDOW = 3          # mỗi email, mỗi 10 phút
OTP_WINDOW_MINUTES = 10
OTP_MAX_PER_IP = 10             # mỗi IP, mỗi 10 phút
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_MINUTES = 15
LOGIN_IP_MAX_FAILURES = 20      # mỗi IP, mỗi 15 phút (trong bộ nhớ)
REFRESH_GRACE_SECONDS = 10      # nhiều tab cùng làm mới một lúc: token vừa xoay vẫn dùng được trong khoảng này

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
GENERIC_LOGIN_ERROR = "Email hoặc mật khẩu không đúng."
GENERIC_OTP_ERROR = "Mã OTP không đúng hoặc đã hết hạn."

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users(
        id UUID PRIMARY KEY,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        failed_attempts INT NOT NULL DEFAULT 0,
        locked_until TIMESTAMPTZ,
        token_version INT NOT NULL DEFAULT 0,
        email_verified_at TIMESTAMPTZ,
        last_login_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS users_email_idx ON users(email)",
    """
    CREATE TABLE IF NOT EXISTS otp_codes(
        id BIGSERIAL PRIMARY KEY,
        email TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK (purpose IN ('register','reset')),
        otp_hmac TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        attempts INT NOT NULL DEFAULT 0,
        used_at TIMESTAMPTZ,
        ip TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS otp_codes_lookup_idx ON otp_codes(email, purpose, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS otp_codes_ip_idx ON otp_codes(ip, created_at DESC)",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS conversations_user_idx ON conversations(user_id, updated_at DESC)",
    "ALTER TABLE security_events ADD COLUMN IF NOT EXISTS user_id UUID",
    "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS user_id UUID",
    "CREATE INDEX IF NOT EXISTS usage_logs_user_idx ON usage_logs(user_id, created_at DESC)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_message_quota INT CHECK (daily_message_quota >= 0)",
    """
    CREATE TABLE IF NOT EXISTS refresh_tokens(
        id BIGSERIAL PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        family_id UUID NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        revoked_at TIMESTAMPTZ,
        ip TEXT,
        user_agent TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS refresh_tokens_user_idx ON refresh_tokens(user_id)",
    "CREATE INDEX IF NOT EXISTS refresh_tokens_family_idx ON refresh_tokens(family_id)",
]


class AuthError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


def ensure_schema() -> None:
    with transaction() as cur:
        for statement in SCHEMA:
            cur.execute(statement)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AuthError(422, "Email không hợp lệ.")
    return email


def _public(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "role": row["role"],
        "is_active": row["is_active"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
        "daily_message_quota": row.get("daily_message_quota"),
    }


def _user_by_email(email: str) -> dict | None:
    rows = query("SELECT * FROM users WHERE email = %s", (email,))
    return rows[0] if rows else None


# ---------------------------- khởi tạo admin ----------------------------

def bootstrap_admin() -> None:
    """Tạo admin đầu tiên từ ADMIN_EMAIL/ADMIN_PASSWORD (không đụng tới tài khoản đã có),
    rồi gán các hội thoại cũ (chưa có chủ) cho admin đó."""
    email = settings.env("ADMIN_EMAIL").lower()
    password = settings.env("ADMIN_PASSWORD")

    if not email or not password:
        if not query("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"):
            logger.warning("Chưa có admin nào: đặt ADMIN_EMAIL và ADMIN_PASSWORD trong .env rồi khởi động lại.")
        return

    email = normalize_email(email)
    problem = passwords.password_problem(password, email)
    if problem:
        raise RuntimeError("ADMIN_PASSWORD không hợp lệ: " + problem)

    # Chỉ tạo khi hệ thống chưa có admin nào: admin có thể đã được đổi email hoặc đổi mật khẩu về sau,
    # khởi động lại không được tạo thêm tài khoản admin thứ hai hay ghi đè gì.
    admin = _user_by_email(email)
    if admin is None and query("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"):
        return
    if admin is None:
        admin_id = str(uuid.uuid4())
        query(
            "INSERT INTO users(id, email, password_hash, role, is_active, email_verified_at) "
            "VALUES (%s, %s, %s, 'admin', TRUE, NOW())",
            (admin_id, email, passwords.hash_password(password)),
            False,
        )
        logger.info("Đã tạo tài khoản admin %s", email)
    else:
        admin_id = str(admin["id"])

    query("UPDATE conversations SET user_id = %s WHERE user_id IS NULL", (admin_id,), False)


# ------------------------------- OTP -------------------------------

def _issue_otp(email: str, purpose: str, ip: str, real: bool) -> str | None:
    """Kiểm tra giới hạn rồi ghi một dòng OTP. real=False (email không dùng được) vẫn ghi dòng
    giả đã 'dùng' để giới hạn và thời gian phản hồi giống hệt trường hợp thật. Trả mã (nếu real)."""
    window_start = _now() - timedelta(minutes=OTP_WINDOW_MINUTES)

    last = query(
        "SELECT created_at FROM otp_codes WHERE email = %s AND purpose = %s ORDER BY id DESC LIMIT 1",
        (email, purpose),
    )
    if last:
        wait = OTP_COOLDOWN_SECONDS - int((_now() - last[0]["created_at"]).total_seconds())
        if wait > 0:
            raise AuthError(429, f"Vui lòng chờ {wait} giây trước khi yêu cầu mã mới.", retry_after=wait)

    per_email = query(
        "SELECT COUNT(*)::int AS n FROM otp_codes WHERE email = %s AND purpose = %s AND created_at > %s",
        (email, purpose, window_start),
    )[0]["n"]
    per_ip = query(
        "SELECT COUNT(*)::int AS n FROM otp_codes WHERE ip = %s AND created_at > %s",
        (ip, window_start),
    )[0]["n"]
    if per_email >= OTP_MAX_PER_WINDOW or per_ip >= OTP_MAX_PER_IP:
        raise AuthError(429, "Bạn đã yêu cầu quá nhiều mã. Thử lại sau ít phút.",
                        retry_after=OTP_WINDOW_MINUTES * 60)

    code = tokens.generate_otp()
    expires = _now() + timedelta(minutes=OTP_TTL_MINUTES)
    with transaction() as cur:
        # Mã mới làm các mã cũ chưa dùng của cùng email/mục đích hết hiệu lực.
        cur.execute(
            "UPDATE otp_codes SET used_at = NOW() WHERE email = %s AND purpose = %s AND used_at IS NULL",
            (email, purpose),
        )
        cur.execute(
            "INSERT INTO otp_codes(email, purpose, otp_hmac, expires_at, used_at, ip) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (email, purpose, tokens.otp_digest(email, purpose, code), expires,
             None if real else _now(), ip),
        )
    return code if real else None


def _check_otp(email: str, purpose: str, code: str) -> None:
    rows = query(
        "SELECT id, otp_hmac, attempts FROM otp_codes "
        "WHERE email = %s AND purpose = %s AND used_at IS NULL AND expires_at > NOW() "
        "ORDER BY id DESC LIMIT 1",
        (email, purpose),
    )
    code = (code or "").strip()
    if not rows or not re.fullmatch(r"\d{6}", code):
        raise AuthError(400, GENERIC_OTP_ERROR)

    row = rows[0]
    if row["attempts"] >= OTP_MAX_ATTEMPTS:
        raise AuthError(400, GENERIC_OTP_ERROR)

    if not tokens.otp_matches(email, purpose, code, row["otp_hmac"]):
        query(
            "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s", (row["id"],), False
        )
        raise AuthError(400, GENERIC_OTP_ERROR)

    query("UPDATE otp_codes SET used_at = NOW() WHERE id = %s", (row["id"],), False)


# ------------------------------ đăng ký ------------------------------

def register_start(email: str, ip: str) -> tuple[str, str, str] | None:
    """Trả (to, subject, body) để gửi nền, hoặc None. Phản hồi cho client luôn giống nhau
    dù email đã có tài khoản hay chưa."""
    email = normalize_email(email)
    mode = settings.registration_mode()

    if mode == "closed":
        raise AuthError(403, "Đăng ký đang đóng. Hãy liên hệ quản trị viên.")
    if mode == "domain":
        domain = email.rsplit("@", 1)[1]
        if domain not in settings.allowed_email_domains():
            raise AuthError(403, "Email này không thuộc danh sách được phép đăng ký.")

    exists = _user_by_email(email) is not None
    code = _issue_otp(email, "register", ip, real=not exists)

    if exists:
        return (email, "Email này đã có tài khoản",
                "Có người vừa yêu cầu đăng ký tài khoản bằng email này, nhưng email đã được đăng ký.\n"
                "Nếu là bạn, hãy dùng chức năng Đăng nhập hoặc Quên mật khẩu. Nếu không phải, bỏ qua thư này.")
    return (email, "Mã xác thực đăng ký",
            f"Mã OTP của bạn là: {code}\nMã có hiệu lực {OTP_TTL_MINUTES} phút và chỉ dùng một lần.\n"
            "Nếu bạn không yêu cầu, hãy bỏ qua thư này.")


def register_verify(email: str, code: str) -> str:
    email = normalize_email(email)
    _check_otp(email, "register", code)
    return tokens.create_flow_token("register", email)


def register_complete(registration_token: str, password: str) -> dict:
    try:
        email = tokens.decode_flow_token(registration_token, "register")["sub"]
    except tokens.TokenError:
        raise AuthError(400, "Phiên đăng ký đã hết hạn. Hãy bắt đầu lại.")

    problem = passwords.password_problem(password, email)
    if problem:
        raise AuthError(422, problem)

    if settings.registration_mode() == "closed":
        raise AuthError(403, "Đăng ký đang đóng. Hãy liên hệ quản trị viên.")

    active = settings.registration_mode() in {"open", "domain"}
    try:
        query(
            "INSERT INTO users(id, email, password_hash, role, is_active, email_verified_at) "
            "VALUES (%s, %s, %s, 'user', %s, NOW())",
            (str(uuid.uuid4()), email, passwords.hash_password(password), active),
            False,
        )
    except Exception as exc:
        if "users_email_idx" in str(exc) or "unique" in str(exc).lower():
            raise AuthError(409, "Phiên đăng ký không còn hiệu lực. Hãy bắt đầu lại.")
        raise

    return {
        "active": active,
        "message": ("Đăng ký thành công. Bạn có thể đăng nhập."
                    if active else "Đăng ký thành công. Tài khoản đang chờ quản trị viên duyệt."),
    }


# ------------------------------ đăng nhập ------------------------------

def login(email: str, password: str, ip: str, user_agent: str = "") -> dict:
    ip_key = f"login-fail:{ip}"
    if ratelimit.count(ip_key, LOGIN_LOCK_MINUTES * 60) >= LOGIN_IP_MAX_FAILURES:
        raise AuthError(429, "Quá nhiều lần thử. Hãy thử lại sau ít phút.", retry_after=LOGIN_LOCK_MINUTES * 60)

    try:
        email = normalize_email(email)
    except AuthError:
        passwords.burn_time(password or "")
        ratelimit.hit(ip_key, 10**6, LOGIN_LOCK_MINUTES * 60)
        raise AuthError(401, GENERIC_LOGIN_ERROR)

    user = _user_by_email(email)

    if user is None:
        passwords.burn_time(password or "")
        ratelimit.hit(ip_key, 10**6, LOGIN_LOCK_MINUTES * 60)
        raise AuthError(401, GENERIC_LOGIN_ERROR)

    if user["locked_until"] and user["locked_until"] > _now():
        wait = int((user["locked_until"] - _now()).total_seconds()) + 1
        raise AuthError(429, "Tài khoản tạm khóa do nhập sai nhiều lần. Hãy thử lại sau ít phút.", retry_after=wait)

    if not passwords.verify_password(password or "", user["password_hash"]):
        failures = user["failed_attempts"] + 1
        locked_until = None
        if failures >= LOGIN_MAX_FAILURES:
            locked_until = _now() + timedelta(minutes=LOGIN_LOCK_MINUTES)
            failures = 0
        query(
            "UPDATE users SET failed_attempts = %s, locked_until = %s, updated_at = NOW() WHERE id = %s",
            (failures, locked_until, user["id"]),
            False,
        )
        ratelimit.hit(ip_key, 10**6, LOGIN_LOCK_MINUTES * 60)
        raise AuthError(401, GENERIC_LOGIN_ERROR)

    if not user["is_active"]:
        raise AuthError(403, "Tài khoản đang chờ quản trị viên duyệt hoặc đã bị vô hiệu hóa.")

    query(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = NOW() WHERE id = %s",
        (user["id"],),
        False,
    )
    return _session_for(_get(str(user["id"])), ip, user_agent)


# ------------------------- phiên: access + refresh -------------------------

def _store_refresh(user_id, family_id: str, ip: str, user_agent: str) -> str:
    raw = tokens.generate_refresh_token()
    query(
        "INSERT INTO refresh_tokens(user_id, family_id, token_hash, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, family_id, tokens.refresh_digest(raw),
         _now() + timedelta(days=settings.refresh_token_days()), ip, (user_agent or "")[:300]),
        False,
    )
    return raw


def _session_for(user: dict, ip: str = "", user_agent: str = "", family_id: str | None = None) -> dict:
    """Access token ngắn hạn (trả cho client giữ trong bộ nhớ) + refresh token (api đặt vào cookie httpOnly)."""
    token, expires_in = tokens.create_access_token(str(user["id"]), user["role"], user["token_version"])
    refresh = _store_refresh(user["id"], family_id or str(uuid.uuid4()), ip, user_agent)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in,
            "user": _public(user), "refresh_token": refresh}


def revoke_user_sessions(user_id) -> None:
    query("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL",
          (user_id,), False)


def refresh_session(raw: str, ip: str = "", user_agent: str = "") -> dict:
    """Đổi refresh token lấy cặp token mới (xoay vòng). Dùng lại token đã xoay (ngoài khoảng ân hạn)
    nghĩa là token có thể bị đánh cắp: thu hồi cả họ token."""
    invalid = AuthError(401, "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.")
    if not raw:
        raise invalid
    rows = query("SELECT * FROM refresh_tokens WHERE token_hash = %s", (tokens.refresh_digest(raw),))
    if not rows:
        raise invalid
    row = rows[0]
    now = _now()

    if row["revoked_at"] is not None or row["expires_at"] <= now:
        raise invalid

    if row["used_at"] is not None:
        if (now - row["used_at"]).total_seconds() > REFRESH_GRACE_SECONDS:
            query("UPDATE refresh_tokens SET revoked_at = NOW() WHERE family_id = %s AND revoked_at IS NULL",
                  (row["family_id"],), False)
            logger.warning("Refresh token bị dùng lại, đã thu hồi cả họ token của user %s", row["user_id"])
            raise invalid
    else:
        query("UPDATE refresh_tokens SET used_at = NOW() WHERE id = %s", (row["id"],), False)

    users = query("SELECT * FROM users WHERE id = %s", (row["user_id"],))
    if not users or not users[0]["is_active"]:
        raise invalid
    return _session_for(users[0], ip, user_agent, family_id=str(row["family_id"]))


def logout_session(raw: str) -> None:
    """Thu hồi cả họ refresh token của thiết bị này. Luôn thành công (không lộ token có hợp lệ hay không)."""
    if not raw:
        return
    query(
        "UPDATE refresh_tokens SET revoked_at = NOW() WHERE revoked_at IS NULL AND family_id IN "
        "(SELECT family_id FROM refresh_tokens WHERE token_hash = %s)",
        (tokens.refresh_digest(raw),), False,
    )


def authenticate(token: str) -> dict:
    """Kiểm tra JWT và đối chiếu lại với database (còn hoạt động, đúng token_version)."""
    try:
        payload = tokens.decode_access_token(token)
        user_id = str(uuid.UUID(payload["sub"]))
    except (tokens.TokenError, ValueError, KeyError):
        raise AuthError(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")

    rows = query("SELECT * FROM users WHERE id = %s", (user_id,))
    user = rows[0] if rows else None
    if (user is None or not user["is_active"]
            or user["token_version"] != payload.get("tv")):
        raise AuthError(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    return _public(user)


# ----------------------------- quên mật khẩu -----------------------------

def forgot_start(email: str, ip: str) -> tuple[str, str, str] | None:
    email = normalize_email(email)
    user = _user_by_email(email)
    code = _issue_otp(email, "reset", ip, real=user is not None)
    if user is None:
        return None  # không gửi thư tới địa chỉ không có tài khoản; phản hồi vẫn giống nhau
    return (email, "Mã đặt lại mật khẩu",
            f"Mã OTP đặt lại mật khẩu của bạn là: {code}\nMã có hiệu lực {OTP_TTL_MINUTES} phút và chỉ dùng một lần.\n"
            "Nếu bạn không yêu cầu, hãy bỏ qua thư này; mật khẩu của bạn không thay đổi.")


def forgot_verify(email: str, code: str) -> str:
    email = normalize_email(email)
    _check_otp(email, "reset", code)
    user = _user_by_email(email)
    if user is None:
        raise AuthError(400, GENERIC_OTP_ERROR)
    return tokens.create_flow_token("reset", email, user["token_version"])


def reset_password(reset_token: str, new_password: str) -> None:
    try:
        payload = tokens.decode_flow_token(reset_token, "reset")
    except tokens.TokenError:
        raise AuthError(400, "Phiên đặt lại mật khẩu đã hết hạn. Hãy bắt đầu lại.")

    email = payload["sub"]
    problem = passwords.password_problem(new_password, email)
    if problem:
        raise AuthError(422, problem)

    user = _user_by_email(email)
    if user is None or user["token_version"] != payload.get("tv"):
        raise AuthError(400, "Phiên đặt lại mật khẩu không còn hiệu lực. Hãy bắt đầu lại.")

    # token_version tăng: token reset này không dùng lại được và mọi phiên đăng nhập cũ hết hiệu lực.
    query(
        "UPDATE users SET password_hash = %s, token_version = token_version + 1, failed_attempts = 0, "
        "locked_until = NULL, updated_at = NOW() WHERE id = %s",
        (passwords.hash_password(new_password), user["id"]),
        False,
    )
    revoke_user_sessions(user["id"])


# --------------------------- quản lý người dùng ---------------------------

def list_users() -> list[dict]:
    rows = query("SELECT * FROM users ORDER BY created_at DESC")
    return [_public(r) for r in rows]


def _get(user_id: str) -> dict:
    try:
        uid = str(uuid.UUID(user_id))
    except ValueError:
        raise AuthError(404, "Không tìm thấy người dùng.")
    rows = query("SELECT * FROM users WHERE id = %s", (uid,))
    if not rows:
        raise AuthError(404, "Không tìm thấy người dùng.")
    return rows[0]


def set_active(actor_id: str, user_id: str, active: bool) -> dict:
    user = _get(user_id)
    if str(user["id"]) == actor_id and not active:
        raise AuthError(400, "Bạn không thể tự vô hiệu hóa tài khoản của mình.")
    query(
        "UPDATE users SET is_active = %s, token_version = token_version + %s, updated_at = NOW() WHERE id = %s",
        (active, 0 if active else 1, user["id"]),
        False,
    )
    if not active:
        revoke_user_sessions(user["id"])
    return _public(_get(user_id))


def set_role(actor_id: str, user_id: str, role: str) -> dict:
    if role not in {"admin", "user"}:
        raise AuthError(422, "Vai trò không hợp lệ.")
    user = _get(user_id)
    if str(user["id"]) == actor_id and role != "admin":
        raise AuthError(400, "Bạn không thể tự hạ quyền của mình.")
    query(
        "UPDATE users SET role = %s, token_version = token_version + 1, updated_at = NOW() WHERE id = %s",
        (role, user["id"]),
        False,
    )
    revoke_user_sessions(user["id"])
    return _public(_get(user_id))


def get_user_detail(user_id: str) -> dict:
    """Thông tin chi tiết cho admin. Không bao giờ trả mật khẩu/hash; nội dung hội thoại vẫn riêng tư,
    admin chỉ thấy số lượng."""
    user = _get(user_id)
    uid = user["id"]
    convs = query("SELECT COUNT(*) AS n FROM conversations WHERE user_id = %s", (uid,))[0]["n"]
    msgs = query(
        "SELECT COUNT(*) AS n FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE c.user_id = %s", (uid,),
    )[0]["n"]
    usage = query(
        "SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens, "
        "COALESCE(SUM(cost_usd), 0) AS cost, MAX(created_at) AS last_at FROM usage_logs WHERE user_id = %s",
        (uid,),
    )[0]
    locked_until = user.get("locked_until")
    now = query("SELECT NOW() AS now")[0]["now"]
    return {
        **_public(user),
        "email_verified_at": user["email_verified_at"].isoformat() if user.get("email_verified_at") else None,
        "updated_at": user["updated_at"].isoformat() if user.get("updated_at") else None,
        "failed_attempts": user["failed_attempts"],
        "locked_until": locked_until.isoformat() if locked_until else None,
        "is_locked": bool(locked_until and locked_until > now),
        "conversation_count": int(convs),
        "message_count": int(msgs),
        "request_count": int(usage["n"]),
        "total_tokens": int(usage["tokens"]),
        "total_cost_usd": float(usage["cost"]),
        "last_request_at": usage["last_at"].isoformat() if usage["last_at"] else None,
        "quota": quota_status(user),
        "groups": groups.groups_of_user(uid),
    }


def admin_set_password(actor: dict, user_id: str, new_password: str) -> tuple[str, str, str]:
    """Admin đặt lại mật khẩu cho người khác. Mọi phiên đăng nhập cũ của họ bị thu hồi và khóa tạm được gỡ.
    Trả mail thông báo (không chứa mật khẩu) để gửi nền."""
    user = _get(user_id)
    if str(user["id"]) == actor["id"]:
        raise AuthError(400, "Hãy dùng chức năng Quên mật khẩu để đổi mật khẩu của chính bạn.")
    problem = passwords.password_problem(new_password, user["email"])
    if problem:
        raise AuthError(422, problem)

    query(
        "UPDATE users SET password_hash = %s, token_version = token_version + 1, failed_attempts = 0, "
        "locked_until = NULL, updated_at = NOW() WHERE id = %s",
        (passwords.hash_password(new_password), user["id"]),
        False,
    )
    revoke_user_sessions(user["id"])
    _audit("admin_password_reset", f"{actor['email']} đã đặt lại mật khẩu cho {user['email']}", user["id"])
    logger.info("Admin %s đặt lại mật khẩu cho %s", actor["email"], user["email"])
    return (user["email"], "Mật khẩu của bạn đã được quản trị viên đặt lại",
            "Quản trị viên vừa đặt lại mật khẩu cho tài khoản của bạn. Các phiên đăng nhập cũ đã bị đăng xuất.\n"
            "Hãy hỏi quản trị viên mật khẩu mới, đăng nhập rồi dùng Quên mật khẩu để đổi sang mật khẩu của riêng bạn.\n"
            "Nếu bạn không biết về việc này, hãy liên hệ quản trị viên ngay.")


def _audit(event_type: str, description: str, user_id=None, severity: str = "low") -> None:
    query(
        "INSERT INTO security_events (request_id, severity, event_type, description, user_id) "
        "VALUES (NULL, %s, %s, %s, %s)",
        (severity, event_type, description, user_id), False,
    )


# ------------------------- đổi mật khẩu (người dùng tự đổi) -------------------------

def change_password(user: dict, current_password: str, new_password: str, ip: str = "",
                    user_agent: str = "") -> tuple[dict, tuple[str, str, str]]:
    """Người dùng tự đổi mật khẩu. Sai mật khẩu hiện tại tính vào khóa tài khoản như khi đăng nhập.
    Mọi phiên (kể cả thiết bị khác) bị thu hồi; thiết bị này nhận phiên mới. Trả (phiên mới, mail thông báo)."""
    row = _get(user["id"])
    if row["locked_until"] and row["locked_until"] > _now():
        wait = int((row["locked_until"] - _now()).total_seconds()) + 1
        raise AuthError(429, "Tài khoản tạm khóa do nhập sai nhiều lần. Hãy thử lại sau ít phút.", retry_after=wait)

    if not passwords.verify_password(current_password or "", row["password_hash"]):
        failures = row["failed_attempts"] + 1
        locked_until = None
        if failures >= LOGIN_MAX_FAILURES:
            locked_until = _now() + timedelta(minutes=LOGIN_LOCK_MINUTES)
            failures = 0
        query("UPDATE users SET failed_attempts = %s, locked_until = %s WHERE id = %s",
              (failures, locked_until, row["id"]), False)
        raise AuthError(400, "Mật khẩu hiện tại không đúng.")

    problem = passwords.password_problem(new_password, row["email"])
    if problem:
        raise AuthError(422, problem)
    if new_password == current_password:
        raise AuthError(422, "Mật khẩu mới phải khác mật khẩu hiện tại.")

    query(
        "UPDATE users SET password_hash = %s, token_version = token_version + 1, failed_attempts = 0, "
        "locked_until = NULL, updated_at = NOW() WHERE id = %s",
        (passwords.hash_password(new_password), row["id"]), False,
    )
    revoke_user_sessions(row["id"])
    _audit("password_changed", f"{row['email']} đã tự đổi mật khẩu", row["id"])
    mail = (row["email"], "Mật khẩu của bạn vừa được đổi",
            "Mật khẩu tài khoản của bạn vừa được đổi và các thiết bị khác đã bị đăng xuất.\n"
            "Nếu không phải bạn, hãy dùng Quên mật khẩu và liên hệ quản trị viên ngay.")
    return _session_for(_get(str(row["id"])), ip, user_agent), mail


# ------------------------------ hạn mức tin nhắn ------------------------------

def _day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """[0h hôm nay, 0h ngày mai) theo múi giờ QUOTA_TIMEZONE, đổi sang UTC."""
    try:
        tz = ZoneInfo(settings.quota_timezone())
    except Exception:
        tz = timezone.utc
    local = (now or _now()).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def quota_limit(user_row: dict) -> int | None:
    """Giới hạn áp dụng cho người này: riêng nếu admin đã đặt, ngược lại mặc định. None = không giới hạn."""
    own = user_row.get("daily_message_quota")
    limit = settings.daily_message_quota() if own is None else own
    return limit or None


def messages_today(user_id) -> int:
    start, end = _day_bounds()
    return query(
        "SELECT COUNT(*)::int AS n FROM usage_logs WHERE user_id = %s AND status = 'success' "
        "AND created_at >= %s AND created_at < %s", (user_id, start, end),
    )[0]["n"]


def quota_status(user_row: dict) -> dict:
    limit = quota_limit(user_row)
    used = messages_today(user_row["id"])
    return {
        "limit": limit,
        "used": used,
        "remaining": None if limit is None else max(0, limit - used),
        "is_default": user_row.get("daily_message_quota") is None,
        "resets_at": _day_bounds()[1].isoformat(),
    }


def check_quota(user: dict) -> None:
    """Ném AuthError 429 khi đã dùng hết số tin nhắn của ngày. Chỉ tin nhắn thành công được tính."""
    row = _get(user["id"])
    limit = quota_limit(row)
    if limit is None or messages_today(row["id"]) < limit:
        return
    wait = max(1, int((_day_bounds()[1] - _now()).total_seconds()))
    raise AuthError(429, f"Bạn đã dùng hết {limit} tin nhắn của hôm nay. Hạn mức được làm mới lúc 0 giờ.",
                    retry_after=wait)


def set_quota(actor: dict, user_id: str, limit: int | None) -> dict:
    """limit None = dùng mặc định chung; 0 = không giới hạn; số dương = giới hạn riêng."""
    user = _get(user_id)
    if limit is not None and (limit < 0 or limit > 1_000_000):
        raise AuthError(422, "Hạn mức không hợp lệ.")
    query("UPDATE users SET daily_message_quota = %s, updated_at = NOW() WHERE id = %s",
          (limit, user["id"]), False)
    label = "mặc định" if limit is None else ("không giới hạn" if limit == 0 else f"{limit} tin nhắn/ngày")
    _audit("quota_changed", f"{actor['email']} đặt hạn mức của {user['email']}: {label}", user["id"])
    return get_user_detail(user_id)


# ---------------------------- xóa tài khoản / đổi email ----------------------------

def delete_user(actor: dict, user_id: str) -> None:
    """Xóa vĩnh viễn tài khoản và hội thoại của họ. Không tự xóa mình, không xóa admin cuối cùng.
    Nhật ký sử dụng và sự kiện bảo mật được giữ lại (chỉ còn id, không còn liên kết)."""
    user = _get(user_id)
    if str(user["id"]) == actor["id"]:
        raise AuthError(400, "Bạn không thể tự xóa tài khoản của mình.")
    if user["role"] == "admin":
        admins = query("SELECT COUNT(*)::int AS n FROM users WHERE role = 'admin'")[0]["n"]
        if admins <= 1:
            raise AuthError(400, "Không thể xóa quản trị viên cuối cùng.")
    with transaction() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user["id"],))
    _audit("user_deleted", f"{actor['email']} đã xóa tài khoản {user['email']}", None, "medium")
    logger.info("Admin %s đã xóa tài khoản %s", actor["email"], user["email"])


def change_email(actor: dict, user_id: str, new_email: str) -> tuple[dict, list[tuple[str, str, str]]]:
    """Admin đổi email của người khác. Phiên cũ bị thu hồi. Trả (user, các mail thông báo)."""
    user = _get(user_id)
    if str(user["id"]) == actor["id"]:
        raise AuthError(400, "Bạn không thể tự đổi email của mình tại đây.")
    new_email = normalize_email(new_email)
    old_email = user["email"]
    if new_email == old_email:
        raise AuthError(422, "Email mới trùng với email hiện tại.")
    if _user_by_email(new_email) is not None:
        raise AuthError(409, "Email này đã được dùng bởi tài khoản khác.")
    try:
        query(
            "UPDATE users SET email = %s, email_verified_at = NULL, token_version = token_version + 1, "
            "updated_at = NOW() WHERE id = %s", (new_email, user["id"]), False,
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise AuthError(409, "Email này đã được dùng bởi tài khoản khác.")
        raise
    revoke_user_sessions(user["id"])
    _audit("admin_email_changed", f"{actor['email']} đổi email {old_email} -> {new_email}", user["id"], "medium")
    note = ("Email đăng nhập của tài khoản bạn đã được quản trị viên đổi từ "
            f"{old_email} sang {new_email}. Các phiên đăng nhập cũ đã bị đăng xuất.")
    return _public(_get(user_id)), [(old_email, "Email tài khoản đã bị đổi", note),
                                    (new_email, "Email tài khoản đã được đổi sang địa chỉ này", note)]


# ------------------------------ thống kê theo người dùng ------------------------------

def usage_by_user() -> list[dict]:
    start, end = _day_bounds()
    rows = query(
        """
        SELECT u.id::text AS id, u.email, u.role, u.is_active, u.daily_message_quota,
               COALESCE(s.requests, 0)::int AS requests,
               COALESCE(s.blocked, 0)::int AS blocked,
               COALESCE(s.errors, 0)::int AS errors,
               COALESCE(s.tokens, 0)::bigint AS tokens,
               COALESCE(s.cost, 0)::float AS cost_usd,
               COALESCE(s.today, 0)::int AS today,
               s.last_at,
               COALESCE(e.n, 0)::int AS security_events
        FROM users u
        LEFT JOIN (
            SELECT user_id,
                   COUNT(*) AS requests,
                   COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
                   COUNT(*) FILTER (WHERE status = 'error') AS errors,
                   SUM(input_tokens + output_tokens) AS tokens,
                   SUM(cost_usd) AS cost,
                   COUNT(*) FILTER (WHERE status = 'success' AND created_at >= %s AND created_at < %s) AS today,
                   MAX(created_at) AS last_at
            FROM usage_logs WHERE user_id IS NOT NULL GROUP BY user_id
        ) s ON s.user_id = u.id
        LEFT JOIN (SELECT user_id, COUNT(*) AS n FROM security_events WHERE user_id IS NOT NULL GROUP BY user_id) e
               ON e.user_id = u.id
        ORDER BY requests DESC, u.email
        """, (start, end),
    )
    out = []
    for r in rows:
        limit = quota_limit({"daily_message_quota": r["daily_message_quota"]})
        out.append({**{k: v for k, v in r.items() if k != "daily_message_quota"},
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                    "quota_limit": limit})
    return out
