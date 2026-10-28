import base64
import hashlib
import uuid
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_db
from .models import Membership, Organization, User
from .schemas import Principal

DEV_USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
DEV_ORG_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")
ROLE_ORDER = ("viewer", "member", "admin", "owner")


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


def signing_secret(settings: Settings) -> str:
    if settings.encryption_key:
        return settings.encryption_key
    if settings.is_production:
        raise RuntimeError("OMNIWEB_ENCRYPTION_KEY is required in production")
    return "local-access-token-secret-change-me"


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    email: str
    name: str
    organization_id: uuid.UUID
    role: str


@lru_cache(maxsize=8)
def jwks_client(discovery_base: str) -> PyJWKClient:
    # Keycloak and most IdPs publish the JWKS location in the discovery document rather than
    # at a fixed path.
    discovery = httpx.get(
        f"{discovery_base.rstrip('/')}/.well-known/openid-configuration", timeout=5
    )
    discovery.raise_for_status()
    return PyJWKClient(discovery.json()["jwks_uri"], cache_keys=True)


def _role(claims: dict) -> str:
    candidates = [claims.get("role", "")]
    candidates += claims.get("realm_access", {}).get("roles", [])
    ranked = [role for role in candidates if role in ROLE_ORDER]
    return max(ranked, key=ROLE_ORDER.index) if ranked else "member"


def decode_oidc(token: str, settings: Settings) -> TokenClaims:
    if not settings.oidc_issuer:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    try:
        signing_key = jwks_client(
            settings.oidc_discovery_url or settings.oidc_issuer
        ).get_signing_key_from_jwt(token)
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(status_code=503, detail="Identity provider unavailable") from exc
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
            name=claims.get("name") or claims.get("preferred_username") or claims.get("email", ""),
            organization_id=uuid.UUID(claims["org_id"]),
            role=_role(claims),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Token is missing tenant claims") from exc


async def resolve_oidc_principal(db: AsyncSession, claims: TokenClaims) -> Principal:
    """The IdP is authoritative for organization membership and role; mirror them locally."""
    organization = await db.get(Organization, claims.organization_id)
    if not organization:
        organization = Organization(
            id=claims.organization_id,
            name=claims.email.split("@")[-1] or "Organization",
            slug=f"org-{claims.organization_id.hex[:12]}",
        )
        db.add(organization)
    user = await db.scalar(select(User).where(User.oidc_subject == claims.subject))
    if not user:
        user = User(
            oidc_subject=claims.subject,
            email=claims.email,
            display_name=claims.name or claims.email,
        )
        db.add(user)
        await db.flush()
    else:
        user.email = claims.email or user.email
        user.display_name = claims.name or user.display_name
    membership = await db.scalar(
        select(Membership).where(
            Membership.organization_id == claims.organization_id, Membership.user_id == user.id
        )
    )
    if not membership:
        db.add(
            Membership(organization_id=claims.organization_id, user_id=user.id, role=claims.role)
        )
    else:
        membership.role = claims.role
    await db.commit()
    return Principal(
        user_id=user.id,
        organization_id=claims.organization_id,
        email=user.email,
        role=claims.role,
        display_name=user.display_name,
        auth_mode="oidc",
    )


async def get_principal(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        try:
            claims = decode_oidc(authorization[7:], settings)
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid access token") from exc
        return await resolve_oidc_principal(db, claims)
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
        display_name="Avery Morgan",
        auth_mode="development",
    )


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return principal
