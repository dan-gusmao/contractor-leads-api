from app.security import create_token, decode_token, hash_password, verify_password

from .conftest import PASSWORD


def test_register_login_and_me(api, client):
    user_id, token = api.register("customer", email="Anna@Example.com")
    r = client.get("/auth/me", headers=api.auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == user_id
    assert body["email"] == "anna@example.com"
    assert body["role"] == "customer"
    assert "password_hash" not in body


def test_email_is_unique_case_insensitively(api, client):
    api.register("customer", email="dup@example.com")
    r = client.post(
        "/auth/register",
        json={"email": "DUP@example.com", "password": PASSWORD, "role": "contractor"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "auth.email_taken"


def test_admin_role_cannot_self_register(client):
    r = client.post(
        "/auth/register", json={"email": "x@example.com", "password": PASSWORD, "role": "admin"}
    )
    assert r.status_code == 403


def test_wrong_password_is_rejected(api, client):
    api.register("customer", email="who@example.com")
    r = client.post("/auth/login", json={"email": "who@example.com", "password": "nope-nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.invalid_credentials"


def test_short_password_fails_validation(client):
    r = client.post(
        "/auth/register", json={"email": "s@example.com", "password": "short", "role": "customer"}
    )
    assert r.status_code == 422


def test_protected_route_requires_token(client):
    assert client.get("/auth/me").status_code == 401
    r = client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.invalid_token"


def test_role_guard(api, client):
    _, customer = api.customer()
    r = client.get("/me/credits", headers=api.auth(customer))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.forbidden"


def test_suspended_user_cannot_log_in_or_use_token(api, client):
    user_id, token = api.register("contractor", email="bad@example.com")
    r = client.patch(
        f"/admin/users/{user_id}/status", json={"status": "suspended"}, headers=api.auth(api.admin())
    )
    assert r.status_code == 200
    assert client.get("/auth/me", headers=api.auth(token)).status_code == 403
    r = client.post("/auth/login", json={"email": "bad@example.com", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.suspended"


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-pass")
    assert stored != "s3cret-pass"
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("other", stored)
    assert not verify_password("s3cret-pass", "not-a-hash")


def test_token_signature_and_expiry():
    token = create_token(7, "k", ttl_seconds=60, now=1_000)
    assert decode_token(token, "k", now=1_030) == 7
    assert decode_token(token, "k", now=1_061) is None
    assert decode_token(token, "other-key", now=1_030) is None
    body, sig = token.split(".")
    assert decode_token(f"{body}x.{sig}", "k", now=1_030) is None
