import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def create_access_token(payload: dict, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire_minutes = expires_minutes or settings.access_token_expire_minutes
    data = payload.copy()
    data["exp"] = int((datetime.now(UTC) + timedelta(minutes=expire_minutes)).timestamp())
    message = _b64url_encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = hmac.new(settings.auth_secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return f"{message}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        message, signature = token.split(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError("token 格式无效") from exc

    expected_sig = hmac.new(settings.auth_secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_encode(expected_sig), signature):
        raise ValueError("token 签名无效")

    payload = json.loads(_b64url_decode(message).decode("utf-8"))
    exp = payload.get("exp")
    if exp is None or int(exp) < int(datetime.now(UTC).timestamp()):
        raise ValueError("token 已过期")
    return payload
