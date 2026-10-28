import base64
import hashlib
import uuid
from dataclasses import dataclass

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient

from .config import Settings, get_settings
from .schemas import Principal

DEV_USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
DEV_ORG_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")


def _cipher(settings: Settings) -> Fernet:
    if settings.encryption_key:
        key = settings.encryption_key.encode()
    elif not settings.is_production:
        key = base64.urlsafe_b64encode(hashlib.sha256(b"omniweb-local-development").digest())
    else:
        raise RuntimeError("OMNIWEB_ENCRYPTION_KEY is required in production")
    return Fernet(key)


def encrypt_secret(value: str, settings: Settings) -> str:
    return _cipher(settings).encrypt(value.encode()).decode()


def decrypt_secret(value: str, settings: Settings) -> str:
    try:
        return _cipher(settings).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored credential cannot be decrypted") from exc


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    email: str
    organization_id: uuid.UUID
    role: str


def _decode_oidc(token: str, settings: Settings) -> TokenClaims:
    if not settings.oidc_issuer:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    client = PyJWKClient(f"{settings.oidc_issuer.rstrip('/')}/.well-known/jwks.json")
    signing_key = client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
        options={"require": ["exp", "iat", "sub"]},
    )
    try:
        return TokenClaims(
            subject=claims["sub"],
            email=claims.get("email", ""),
            organization_id=uuid.UUID(claims["org_id"]),
            role=claims.get("role", "member"),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Token is missing tenant claims") from exc


async def get_principal(
    request: Request, settings: Settings = Depends(get_settings)
) -> Principal:
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        try:
            claims = _decode_oidc(authorization[7:], settings)
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid access token") from exc
        # User records are resolved by OIDC subject in production. The stable UUID claim is optional.
        user_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{settings.oidc_issuer}/{claims.subject}")
        return Principal(
            user_id=user_id,
            organization_id=claims.organization_id,
            email=claims.email,
            role=claims.role,
        )
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required",
        )
    return Principal(
        user_id=DEV_USER_ID,
        organization_id=DEV_ORG_ID,
        email="dev@omniweb.local",
        role="owner",
    )


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return principal
