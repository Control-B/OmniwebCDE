"""Client for the Adaptive AI Execution Engine (AAEE).

The control plane is the only AAEE caller. Every request carries a short-lived service token whose
claims (organization, user, project, role, platform administrator) come from the authenticated
principal, never from browser input.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import HTTPException

from ..config import Settings
from ..schemas import Principal

AUDIENCE = "omniweb-aaee"
DEV_AAEE_SECRET = "local-development-aaee-secret-change-me"  # noqa: S105  rejected in production
SETTLED = {
    "awaiting_caller",
    "awaiting_validation",
    "awaiting_approval",
    "blocked",
    "completed",
    "failed",
    "cancelled",
    "needs_human",
    "planned",
}


class Unavailable(Exception):
    """AAEE could not be reached. Callers may fall back to the direct gateway path."""


def secret(settings: Settings) -> str:
    if settings.aaee_secret:
        return settings.aaee_secret
    if settings.is_production:
        raise RuntimeError("OMNIWEB_AAEE_SECRET is required in production")
    return DEV_AAEE_SECRET


def is_platform_admin(settings: Settings, principal: Principal) -> bool:
    allowed = {item.strip().lower() for item in settings.platform_admins.split(",") if item.strip()}
    if str(principal.user_id).lower() in allowed or principal.email.lower() in allowed:
        return True
    # The single local development identity administers its own development platform.
    return (
        not settings.is_production
        and principal.auth_mode == "development"
        and principal.role == "owner"
    )


def service_token(
    settings: Settings,
    principal: Principal,
    project_id: uuid.UUID | None = None,
    service: str = "control-plane",
) -> str:
    issued = datetime.now(UTC)
    claims: dict[str, Any] = {
        "aud": AUDIENCE,
        "org": str(principal.organization_id),
        "user": str(principal.user_id),
        "role": principal.role,
        "padmin": is_platform_admin(settings, principal),
        "svc": service,
        "iat": issued,
        "exp": issued + timedelta(minutes=3),
    }
    if project_id:
        claims["project"] = str(project_id)
    return jwt.encode(claims, secret(settings), algorithm="HS256")


_AsyncClient = httpx.AsyncClient


def http_client(settings: Settings, timeout: float) -> httpx.AsyncClient:
    return _AsyncClient(base_url=settings.aaee_url, timeout=timeout)


async def call(
    settings: Settings,
    principal: Principal,
    method: str,
    path: str,
    *,
    project_id: uuid.UUID | None = None,
    json: Any = None,
    params: dict | None = None,
    timeout: float = 150,
    service: str = "control-plane",
) -> Any:
    if not settings.aaee_enabled:
        raise Unavailable("AAEE is disabled")
    headers = {"Authorization": f"Bearer {service_token(settings, principal, project_id, service)}"}
    try:
        async with http_client(settings, timeout) as client:
            response = await client.request(method, path, headers=headers, json=json, params=params)
    except httpx.HTTPError as exc:
        raise Unavailable("The AI execution engine is unavailable") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": "Unexpected AI execution engine response"}
    if response.status_code >= 400:
        detail = (
            payload.get("detail", "AI execution engine error")
            if isinstance(payload, dict)
            else "AI execution engine error"
        )
        raise HTTPException(status_code=response.status_code, detail=detail)
    return payload


async def proxy(
    settings: Settings, principal: Principal, method: str, path: str, **kwargs: Any
) -> Any:
    """For API routes: an unreachable engine is a 503 rather than a fallback."""
    try:
        return await call(settings, principal, method, path, **kwargs)
    except Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def submit(
    settings: Settings,
    principal: Principal,
    body: dict,
    *,
    project_id: uuid.UUID | None = None,
    wait: float = 120,
    service: str = "builder",
) -> dict:
    task = await call(
        settings,
        principal,
        "POST",
        "/v1/tasks",
        project_id=project_id,
        json=body,
        params={"wait": min(wait, 300)},
        timeout=wait + 30,
        service=service,
    )
    return await settle(
        settings, principal, task, project_id=project_id, timeout=wait, service=service
    )


async def settle(
    settings: Settings,
    principal: Principal,
    task: dict,
    *,
    project_id: uuid.UUID | None = None,
    timeout: float = 120,
    service: str = "builder",
) -> dict:
    """Polls until the task needs the caller, a human, or has finished."""
    deadline = asyncio.get_running_loop().time() + timeout
    while task["status"] not in SETTLED and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.5)
        task = await call(
            settings,
            principal,
            "GET",
            f"/v1/tasks/{task['id']}",
            project_id=project_id,
            service=service,
        )
    return task


async def validate(
    settings: Settings,
    principal: Principal,
    task: dict,
    execution_id: str,
    report: dict,
    *,
    project_id: uuid.UUID | None = None,
    wait: float = 120,
) -> dict:
    result = await call(
        settings,
        principal,
        "POST",
        f"/v1/tasks/{task['id']}/validation",
        project_id=project_id,
        json={"execution_id": execution_id, "report": report},
        service="builder",
    )
    return await settle(settings, principal, result, project_id=project_id, timeout=wait)


EVIDENCE_KIND = {
    "typecheck": "typecheck",
    "test": "unit_tests",
    "build": "build",
    "migrations": "migrations",
    "openapi": "openapi",
    "lint": "lint",
}


def evidence_from_checks(steps: list[dict]) -> list[dict]:
    """Maps builder sandbox check results to AAEE evidence items."""
    items = []
    for step in steps[:60]:
        target, _, suffix = step["name"].partition(".")
        kind = next(
            (kind for key, kind in EVIDENCE_KIND.items() if key in suffix), "integration_tests"
        )
        if kind == "unit_tests" and target == "api":
            kind = "api_tests"
        items.append(
            {
                "name": step["name"][:80],
                "kind": kind,
                "status": "passed" if step["ok"] else "failed",
                "duration_ms": int(step.get("duration", 0) * 1000),
                "output": (step.get("output") or "")[-20_000:],
                "target": step.get("target"),
            }
        )
    return items
