import base64
import hashlib
import uuid
from dataclasses import dataclass

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request

from .config import Settings, get_settings

AUDIENCE = "omniweb-model-gateway"
DEV_SERVICE_SECRET = "local-development-gateway-secret-change-me"  # noqa: S105  rejected in production


def service_secret(settings: Settings) -> str:
    if settings.service_secret:
        return settings.service_secret
    if settings.is_production:
        raise RuntimeError("GATEWAY_SERVICE_SECRET is required in production")
    return DEV_SERVICE_SECRET


def _cipher(settings: Settings) -> Fernet:
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    if settings.is_production:
        raise RuntimeError("GATEWAY_ENCRYPTION_KEY is required in production")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"omniweb-gateway-local").digest()))


def encrypt(value: str, settings: Settings) -> str:
    return _cipher(settings).encrypt(value.encode()).decode()


def decrypt(value: str, settings: Settings) -> str:
    return _cipher(settings).decrypt(value.encode()).decode()


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:10]


@dataclass(frozen=True)
class Caller:
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    role: str


def caller(request: Request, settings: Settings = Depends(get_settings)) -> Caller:
    """Only the control plane can call the gateway; it signs a short-lived token per request."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Service token required")
    try:
        claims = jwt.decode(
            header[7:],
            service_secret(settings),
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "iat", "org"]},
        )
        return Caller(
            organization_id=uuid.UUID(claims["org"]),
            user_id=uuid.UUID(claims["user"]) if claims.get("user") else None,
            project_id=uuid.UUID(claims["project"]) if claims.get("project") else None,
            role=claims.get("role", "member"),
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid service token") from exc


def admin_caller(identity: Caller = Depends(caller)) -> Caller:
    if identity.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return identity
