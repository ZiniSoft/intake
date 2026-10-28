"""Checks for the few routes reached by a flow outside Intake rather than by a signed-in person (ADR-0038, ADR-0039).

Each such route has its own secret in the server's environment. A secret that is unset or short closes the route:
it answers 404, as if it were not there.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import status

from app.api.errors import api_exception

# A secret shorter than this is treated as not set: a short one can be guessed.
MIN_SECRET = 24
# How far the clock of the caller may be from ours, and so how long a captured call can be replayed.
MAX_SKEW_SECONDS = 300


def configured(value: str | None) -> str:
    secret = (value or "").strip()
    if len(secret) < MIN_SECRET:
        raise api_exception(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Not found")
    return secret


def denied(code: str) -> None:
    raise api_exception(status.HTTP_401_UNAUTHORIZED, code, "Invalid credentials")


def check_bearer(secret: str, authorization: str, code: str) -> None:
    given = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(given.encode(), secret.encode()):
        denied(code)


def check_signature(secret: str, timestamp: str, signature: str, body: bytes, code: str) -> None:
    """`signature` is the hex HMAC-SHA256 of `<timestamp>.<raw body>`; the timestamp is Unix seconds, close to now."""
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
        denied(code)
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.strip().lower().encode(), expected.encode()):
        denied(code)
