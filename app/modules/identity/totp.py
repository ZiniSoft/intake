from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def verify_code(secret: str, code: str, now: int | None = None) -> bool:
    if not code.isdigit() or len(code) != 6:
        return False
    timestamp = int(time.time()) if now is None else now
    for offset in (-30, 0, 30):
        counter = (timestamp + offset) // 30
        digest = hmac.new(
            base64.b32decode(secret + "=" * (-len(secret) % 8)),
            struct.pack(">Q", counter),
            hashlib.sha1,
        ).digest()
        index = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[index : index + 4])[0] & 0x7FFFFFFF
        expected = f"{value % 1_000_000:06d}"
        if hmac.compare_digest(expected, code):
            return True
    return False