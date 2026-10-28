import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import HTTPException

from ..config import Settings
from ..schemas import Principal

AUDIENCE = "omniweb-model-gateway"
DEV_GATEWAY_SECRET = "local-development-gateway-secret-change-me"  # noqa: S105  rejected in production


def gateway_secret(settings: Settings) -> str:
    if settings.model_gateway_secret:
        return settings.model_gateway_secret
    if settings.is_production:
        raise RuntimeError("OMNIWEB_MODEL_GATEWAY_SECRET is required in production")
    return DEV_GATEWAY_SECRET


def service_token(settings: Settings, principal: Principal, project_id: uuid.UUID | None = None) -> str:
    issued = datetime.now(UTC)
    claims: dict[str, Any] = {
        "aud": AUDIENCE,
        "org": str(principal.organization_id),
        "user": str(principal.user_id),
        "role": principal.role,
        "iat": issued,
        "exp": issued + timedelta(minutes=3),
    }
    if project_id:
        claims["project"] = str(project_id)
    return jwt.encode(claims, gateway_secret(settings), algorithm="HS256")


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
) -> Any:
    headers = {"Authorization": f"Bearer {service_token(settings, principal, project_id)}"}
    try:
        async with httpx.AsyncClient(base_url=settings.model_gateway_url, timeout=timeout) as client:
            response = await client.request(method, path, headers=headers, json=json, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="The model gateway is unavailable") from exc
    if response.status_code == 204:
        return None
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": "Unexpected gateway response"}
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=payload.get("detail", "Gateway error"))
    return payload
