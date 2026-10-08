import time

import jwt
import pytest

from app.core import settings, tokens


def test_access_token_roundtrip():
    token, seconds = tokens.create_access_token("user-1", "admin", 3)
    payload = tokens.decode_access_token(token)
    assert (payload["sub"], payload["role"], payload["tv"]) == ("user-1", "admin", 3)
    assert seconds == 60 * 60


def test_tampered_or_foreign_token_is_rejected():
    token, _ = tokens.create_access_token("u", "user", 0)
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(token[:-2] + "xx")
    forged = jwt.encode({"sub": "u", "typ": "access", "iat": 1, "exp": int(time.time()) + 60},
                        "another-secret-another-secret-12345", algorithm="HS256")
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(forged)


def test_expired_token_is_rejected():
    now = int(time.time())
    old = jwt.encode({"sub": "u", "typ": "access", "iat": now - 100, "exp": now - 10},
                     settings.jwt_secret(), algorithm="HS256")
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(old)


def test_alg_none_is_rejected():
    now = int(time.time())
    unsigned = jwt.encode({"sub": "u", "typ": "access", "iat": now, "exp": now + 60}, None, algorithm="none")
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(unsigned)


def test_flow_tokens_are_not_interchangeable():
    reset = tokens.create_flow_token("reset", "a@b.com", 1)
    register = tokens.create_flow_token("register", "a@b.com")
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(reset)          # token đặt lại mật khẩu không dùng để đăng nhập
    with pytest.raises(tokens.TokenError):
        tokens.decode_flow_token(register, "reset")
    assert tokens.decode_flow_token(reset, "reset")["tv"] == 1


def test_otp_is_six_digits_and_hmac_bound_to_email_and_purpose():
    code = tokens.generate_otp()
    assert len(code) == 6 and code.isdigit()
    digest = tokens.otp_digest("a@b.com", "register", code)
    assert code not in digest
    assert tokens.otp_matches("A@B.com", "register", code, digest)      # không phân biệt hoa thường
    assert not tokens.otp_matches("a@b.com", "reset", code, digest)      # đúng mã nhưng sai mục đích
    assert not tokens.otp_matches("c@d.com", "register", code, digest)
    assert not tokens.otp_matches("a@b.com", "register", "000000" if code != "000000" else "111111", digest)


@pytest.mark.parametrize("secret", ["", "short", "change-me-" + "x" * 40, "Replace-this-" + "y" * 40])
def test_service_refuses_weak_or_sample_secret(monkeypatch, secret):
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError):
        settings.validate()


def test_service_accepts_strong_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "q8Zr-7vLw2pX9sKd4mNc1aTb6yHe3uJf0gRi5oV")
    settings.validate()
