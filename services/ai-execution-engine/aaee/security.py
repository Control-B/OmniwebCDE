"""Service authentication, redaction, rate limiting, and audit logging."""

import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .models import AuditEvent

AUDIENCE = "omniweb-aaee"
DEV_SERVICE_SECRET = "local-development-aaee-secret-change-me"  # noqa: S105  rejected in production
ADMIN_ROLES = {"owner", "admin"}


def service_secret(settings: Settings) -> str:
    if settings.service_secret:
        return settings.service_secret
    if settings.is_production:
        raise RuntimeError("AAEE_SERVICE_SECRET is required in production")
    return DEV_SERVICE_SECRET


@dataclass(frozen=True)
class Caller:
    """Identity asserted by the control plane. Nothing here can come from a request body."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    role: str
    platform_admin: bool = False
    service: str = "control-plane"

    @property
    def tenant_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def caller(request: Request, settings: Settings = Depends(get_settings)) -> Caller:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Service token required")
    try:
        claims = jwt.decode(header[7:], service_secret(settings), algorithms=["HS256"], audience=AUDIENCE, options={"require": ["exp", "iat", "org"]})
        return Caller(
            tenant_id=uuid.UUID(claims["org"]),
            user_id=uuid.UUID(claims["user"]) if claims.get("user") else None,
            project_id=uuid.UUID(claims["project"]) if claims.get("project") else None,
            role=str(claims.get("role", "member")),
            platform_admin=bool(claims.get("padmin", False)),
            service=str(claims.get("svc", "control-plane"))[:32],
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid service token") from exc


def tenant_admin(identity: Caller = Depends(caller)) -> Caller:
    if not identity.tenant_admin and not identity.platform_admin:
        raise HTTPException(status_code=403, detail="Organization administrator role required")
    return identity


def platform_admin(identity: Caller = Depends(caller)) -> Caller:
    if not identity.platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required")
    return identity


# Secrets that must never reach logs, events, diagnostics, or prompts sent back to callers.
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:proj-|ant-|or-v1-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bdop_v1_[a-f0-9]{40,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)(\s*[:=]\s*)(['\"]?)[^\s'\"]{8,}\3"),
]


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def find_secrets(text: str) -> list[str]:
    hits = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            hits.append(match.group(0)[:6] + "…")
    return hits


class RateLimiter:
    """Per-tenant sliding window. Uses Redis when configured so limits hold across replicas."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._local: dict[str, deque[float]] = defaultdict(deque)
        self._redis = None
        if settings.redis_url:
            import redis.asyncio as redis

            self._redis = redis.from_url(settings.redis_url)

    async def check(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        if self._redis is not None:
            try:
                bucket = f"aaee:rl:{key}:{int(time.time() // window_seconds)}"
                count = await self._redis.incr(bucket)
                if count == 1:
                    await self._redis.expire(bucket, window_seconds)
                return count <= limit
            except Exception:  # noqa: S110  fall back to the local window when Redis is down
                pass
        now = time.monotonic()
        window = self._local[key]
        while window and now - window[0] > window_seconds:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


async def audit(db: AsyncSession, actor: Caller | str, action: str, target: str = "", details: dict | None = None) -> None:
    if isinstance(actor, Caller):
        tenant = actor.tenant_id
        name = f"{'platform-admin' if actor.platform_admin else actor.role}:{actor.user_id or actor.service}"
    else:
        tenant, name = None, actor
    db.add(AuditEvent(tenant_id=tenant, actor=name[:80], action=action, target=target[:200], details=details or {}))
