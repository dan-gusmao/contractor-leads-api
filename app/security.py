"""Password hashing and signed access tokens (standard library only)."""

import base64
import hashlib
import hmac
import json
import secrets
import time

PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_token(user_id: int, secret: str, ttl_seconds: int, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    body = _b64(json.dumps({"sub": user_id, "exp": issued + ttl_seconds}).encode())
    return f"{body}.{sign(body.encode(), secret)}"


def decode_token(token: str, secret: str, now: float | None = None) -> int | None:
    """Return the user id for a valid, unexpired token, else ``None``."""
    try:
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, sign(body.encode(), secret)):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    current = now if now is not None else time.time()
    if claims.get("exp", 0) < current:
        return None
    return int(claims["sub"])
