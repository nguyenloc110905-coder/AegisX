import hashlib
import secrets


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


def digest_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
