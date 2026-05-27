"""Local username/password authentication helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Response

from . import postgres_store
from .config import CSRF_PROTECTION_ENABLED, SECURE_COOKIES

SESSION_COOKIE_NAME = "llm_council_session"
CSRF_COOKIE_NAME = "llm_council_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SESSION_DAYS = 30
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 310_000
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {
    "/api/auth/bootstrap",
    "/api/auth/login",
}


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    """Hash a password using stdlib PBKDF2."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored PBKDF2 hash."""
    try:
        prefix, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        algorithm = prefix.removeprefix("pbkdf2_")
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except Exception:
        return False

    if algorithm != PBKDF2_ALGORITHM:
        return False

    candidate = hashlib.pbkdf2_hmac(
        algorithm,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def hash_session_token(token: str) -> str:
    """Hash an opaque session token before persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_csrf_token() -> str:
    """Create an opaque browser-visible CSRF token."""
    return secrets.token_urlsafe(32)


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Return non-sensitive user fields."""
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user.get("created_at"),
    }


def auth_status() -> Dict[str, Any]:
    """Return auth bootstrap status."""
    configured = postgres_store.ensure_database()
    has_users = postgres_store.count_users() > 0 if configured else False
    return {
        "configured": configured,
        "bootstrap_required": configured and not has_users,
    }


def create_session(response: Response, user: Dict[str, Any]) -> None:
    """Create a persistent browser session and attach it as an HttpOnly cookie."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    created = postgres_store.create_user_session(
        user["id"],
        hash_session_token(token),
        expires_at,
    )
    if not created:
        raise HTTPException(status_code=503, detail="Could not create session")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        expires=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    set_csrf_cookie(response)


def set_csrf_cookie(response: Response, token: Optional[str] = None) -> str:
    """Attach a browser-readable CSRF token cookie."""
    csrf_token = token or create_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        expires=SESSION_DAYS * 24 * 60 * 60,
        httponly=False,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    return csrf_token


def clear_session(request: Request, response: Response) -> None:
    """Delete the current session cookie and persisted session row."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        postgres_store.delete_user_session(hash_session_token(token))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def validate_csrf_request(request: Request) -> None:
    """Validate double-submit CSRF token for authenticated unsafe requests."""
    if not CSRF_PROTECTION_ENABLED:
        return
    if request.method.upper() not in UNSAFE_METHODS:
        return
    if request.url.path in CSRF_EXEMPT_PATHS:
        return
    if not request.cookies.get(SESSION_COOKIE_NAME):
        return

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token:
        raise HTTPException(status_code=403, detail="CSRF token required")
    if not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Load the authenticated user for a request, if any."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return postgres_store.get_user_for_session(hash_session_token(token))


def require_user(request: Request) -> Dict[str, Any]:
    """FastAPI dependency requiring a valid local session."""
    user = get_optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request) -> Dict[str, Any]:
    """FastAPI dependency requiring an admin local session."""
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return user
