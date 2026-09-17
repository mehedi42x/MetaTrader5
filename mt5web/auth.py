"""Authentication: web passcode session tokens + bridge agent keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from .config import settings
from .crypto import new_token
from .store import data


def _key() -> bytes:
    return settings.secret_key()


def _pad(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.new(_key(), payload, hashlib.sha256).digest()).decode().rstrip("=")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(role: str, ttl: int = 7 * 24 * 3600, name: str = "") -> str:
    body = _b64encode(json.dumps({"r": role, "n": name, "exp": int(time.time()) + ttl}).encode())
    return f"{body}.{_sign(body.encode())}"


def verify_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    body, _, signature = token.rpartition(".")
    if not hmac.compare_digest(_sign(body.encode()), signature):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return payload


# --------------------------------------------------------------------------- #
# passcode
# --------------------------------------------------------------------------- #


def hash_passcode(raw: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt.encode(), 120_000)
    return f"pbkdf2${salt}${_b64encode(digest)}"


def check_passcode(raw: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt.encode(), 120_000)
    except ValueError:
        return hmac.compare_digest(raw, stored)  # allow plaintext in an emergency
    return hmac.compare_digest(_b64encode(candidate), digest)


def passcode_is_set() -> bool:
    if settings.expected_passcode():
        return True
    return bool(data.config.read().get("passcode_hash"))


def verify_passcode(raw: str) -> bool:
    env_pass = settings.expected_passcode()
    if env_pass:
        return hmac.compare_digest(raw.encode(), env_pass.encode())
    stored = data.config.read().get("passcode_hash", "")
    if not stored:
        return False
    return check_passcode(raw, stored)


def set_passcode(raw: str) -> None:
    def _update(cfg: dict) -> None:
        cfg["passcode_hash"] = hash_passcode(raw)
        cfg["passcode_set_at"] = time.time()

    data.config.mutate(_update)


def needs_setup() -> bool:
    return not passcode_is_set() and not settings.expected_passcode()


# --------------------------------------------------------------------------- #
# bridge (agent) keys
# --------------------------------------------------------------------------- #


def ensure_bridge_key() -> str:
    """Return the agent key, generating one on first use."""
    env_key = settings.expected_bridge_key()
    if env_key:
        return env_key

    def _get(cfg: dict) -> str:
        if not cfg.get("bridge_key"):
            cfg["bridge_key"] = new_token(16)
            cfg["bridge_key_created_at"] = time.time()
        return cfg["bridge_key"]

    return data.config.mutate(_get)


def verify_bridge_key(candidate: str) -> bool:
    expected = ensure_bridge_key()
    return hmac.compare_digest(candidate.encode(), expected.encode())


def rotate_bridge_key() -> str:
    def _rotate(cfg: dict) -> str:
        cfg["bridge_key"] = new_token(16)
        cfg["bridge_key_created_at"] = time.time()
        return cfg["bridge_key"]

    return data.config.mutate(_rotate)


def token_from_request(authorization: str | None, query_token: str | None = None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (query_token or "").strip()
