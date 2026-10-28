"""Client for the Omniweb model gateway.

The gateway is the only component holding provider credentials and calling providers.
AAEE pins a specific model per attempt (no gateway-side fallback) and attributes each call
to a task and execution so both ledgers reconcile.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
import jwt

from .config import Settings
from .security import Caller

GATEWAY_AUDIENCE = "omniweb-model-gateway"
DEV_GATEWAY_SECRET = "local-development-gateway-secret-change-me"  # noqa: S105  rejected in production


class GatewayError(Exception):
    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind = kind  # budget | no_model | provider_error | timeout | cancelled | unavailable | rejected
        self.status = status


@dataclass
class ChatResult:
    content: str
    provider: str
    model_id: str
    billing_model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float
    latency_ms: int
    request_id: str
    development_model: bool = False


class Gateway(Protocol):
    async def models(self, identity: Caller) -> list[dict]: ...
    async def budgets(self, identity: Caller, project_id: uuid.UUID | None) -> list[dict]: ...
    async def chat(self, identity: Caller, project_id: uuid.UUID | None, *, model: str, messages: list[dict], max_output_tokens: int,
                   task_budget_usd: float, response_format: dict | None, request_id: str, attribution: dict) -> ChatResult: ...
    async def cancel(self, identity: Caller, request_id: str) -> None: ...


class HttpGateway:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def _secret(self) -> str:
        if self.settings.gateway_secret:
            return self.settings.gateway_secret
        if self.settings.is_production:
            raise RuntimeError("AAEE_GATEWAY_SECRET is required in production")
        return DEV_GATEWAY_SECRET

    def _headers(self, identity: Caller, project_id: uuid.UUID | None) -> dict:
        now = datetime.now(UTC)
        claims = {"org": str(identity.tenant_id), "role": identity.role, "aud": GATEWAY_AUDIENCE, "iat": now,
                  "exp": now + timedelta(seconds=self.settings.gateway_timeout_seconds + 60)}
        if identity.user_id:
            claims["user"] = str(identity.user_id)
        if project_id:
            claims["project"] = str(project_id)
        return {"Authorization": f"Bearer {jwt.encode(claims, self._secret(), algorithm='HS256')}"}

    async def _request(self, method: str, path: str, identity: Caller, project_id: uuid.UUID | None = None, **kwargs) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self.settings.gateway_url, transport=self.transport,
                                         timeout=self.settings.gateway_timeout_seconds) as client:
                return await client.request(method, path, headers=self._headers(identity, project_id), **kwargs)
        except httpx.TimeoutException as exc:
            raise GatewayError("timeout", "Model gateway timed out") from exc
        except httpx.HTTPError as exc:
            raise GatewayError("unavailable", "Model gateway is unreachable") from exc

    async def models(self, identity: Caller) -> list[dict]:
        response = await self._request("GET", "/v1/models", identity, params={"routable_only": "true"})
        if response.status_code != 200:
            raise GatewayError("unavailable", f"Model list failed ({response.status_code})", response.status_code)
        return response.json()

    async def budgets(self, identity: Caller, project_id: uuid.UUID | None) -> list[dict]:
        response = await self._request("GET", "/v1/budgets", identity, project_id)
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise GatewayError("unavailable", f"Budget lookup failed ({response.status_code})", response.status_code)
        return response.json().get("budgets", [])

    async def chat(self, identity, project_id, *, model, messages, max_output_tokens, task_budget_usd, response_format, request_id,
                   attribution) -> ChatResult:
        body = {
            "messages": messages, "model": model, "max_output_tokens": max_output_tokens,
            "task_budget_usd": round(max(task_budget_usd, 0.000001), 6), "agent": attribution.get("agent", "aaee"),
            "request_id": request_id, "task_id": attribution.get("task_id"), "execution_id": attribution.get("execution_id"),
            "strategy": attribution.get("strategy"),
        }
        if response_format:
            body["response_format"] = response_format
        response = await self._request("POST", "/v1/chat", identity, project_id, json=body)
        if response.status_code == 402:
            raise GatewayError("budget", "Organization or project budget exhausted", 402)
        if response.status_code == 422:
            raise GatewayError("no_model", _detail(response), 422)
        if response.status_code == 499:
            raise GatewayError("cancelled", "Request cancelled", 499)
        if response.status_code >= 400:
            kind = "timeout" if "timeout" in response.text else "provider_error"
            raise GatewayError(kind, _detail(response), response.status_code)
        data = response.json()
        usage = data.get("usage", {})
        return ChatResult(
            content=data.get("content", ""), provider=data["provider"], model_id=data["model_id"],
            billing_model=data.get("billing_model", "platform"), input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0), cached_tokens=usage.get("cached_tokens", 0),
            cost_usd=float(usage.get("cost_usd", 0)), latency_ms=int(usage.get("latency_ms", 0)), request_id=data.get("request_id", request_id),
            development_model=bool(data.get("development_model")),
        )

    async def cancel(self, identity: Caller, request_id: str) -> None:
        try:
            await self._request("POST", f"/v1/requests/{request_id}/cancel", identity)
        except GatewayError:
            pass


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"Gateway error {response.status_code}"
    if isinstance(detail, dict):
        detail = detail.get("message", "")
    return str(detail)[:300]
