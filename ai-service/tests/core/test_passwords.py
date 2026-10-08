from app.core import passwords


def test_hash_is_salted_and_verifies():
    a = passwords.hash_password("Correct-horse-9")
    b = passwords.hash_password("Correct-horse-9")
    assert a != b and a.startswith("scrypt$")
    assert passwords.verify_password("Correct-horse-9", a)
    assert not passwords.verify_password("Correct-horse-8", a)


def test_verify_rejects_garbage_hash():
    assert not passwords.verify_password("x", "not-a-hash")
    assert not passwords.verify_password("x", "bcrypt$1$2$3$4$5")


def test_password_policy():
    assert passwords.password_problem("short1") is not None
    assert passwords.password_problem("1234567890") is not None          # chỉ có số
    assert passwords.password_problem("aaaaaaaaaaaa") is not None        # quá ít ký tự khác nhau
    assert passwords.password_problem("a@b.com-a@b.com", "a@b.com-a@b.com") is not None  # trùng email
    assert passwords.password_problem("x" * 129) is not None
    assert passwords.password_problem("Tot-hon-nhieu-9") is None
