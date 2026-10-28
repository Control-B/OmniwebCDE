import asyncio
import ipaddress
import logging
import socket
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from . import budgets as budget_service
from .config import Settings, get_settings
from .database import SessionLocal, engine, get_db
from .inference import ProviderError, complete, cost, estimate_tokens
from .models import (
    ADDED_COLUMNS,
    Base,
    BudgetAlert,
    ModelEntry,
    ProviderCredential,
    RoutingPreference,
    UsageRecord,
)
from .providers import DEV_PROVIDER, PROVIDERS, discover
from .registry import PLATFORM, credentials_for, refresh, seed_dev_models
from .routing import (
    COMPLEXITY_TIER,
    DEFAULT_CONTEXT,
    TIERS,
    RouteRequest,
    candidates,
    escalation_path,
    worst_case_cost,
)
from .security import Caller, admin_caller, caller, encrypt, fingerprint

logger = logging.getLogger("omniweb.gateway")
INFLIGHT: dict[str, tuple[uuid.UUID, asyncio.Task]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_add_missing_columns)
    async with SessionLocal() as db:
        await seed_dev_models(db, settings)
    yield
    await engine.dispose()


def _add_missing_columns(connection) -> None:
    inspector = inspect(connection)
    for table, columns in ADDED_COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name, kind in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))


app = FastAPI(title="Omniweb Model Gateway", version="0.1.0", lifespan=lifespan)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=200_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    tier: Literal["economy", "standard", "advanced", "self_hosted"] | None = None
    complexity: Literal["simple", "normal", "complex"] | None = None
    capabilities: list[str] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, ge=1, le=64_000)
    task_budget_usd: float | None = Field(default=None, gt=0, le=100)
    agent: str = Field(default="assistant", max_length=64)
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    response_format: dict | None = None
    # A pinned "provider/model_id" runs exactly that model with no fallback. The AI execution
    # engine uses this because it makes the routing decision and accounts for each attempt.
    model: str | None = Field(default=None, max_length=240)
    task_id: str | None = Field(default=None, max_length=40)
    execution_id: str | None = Field(default=None, max_length=40)
    strategy: str | None = Field(default=None, max_length=24)


class CredentialInput(BaseModel):
    api_key: SecretStr | None = None
    base_url: str = Field(default="", max_length=300)


class BudgetInput(BaseModel):
    scope: Literal["organization_monthly", "project"]
    limit_usd: float = Field(ge=0, le=100_000)
    hard_limit: bool = True
    alert_threshold: float = Field(default=0.8, gt=0, le=1)


class PreferenceInput(BaseModel):
    default_tier: Literal["economy", "standard", "advanced", "self_hosted"] = "standard"
    allowed_providers: list[str] = Field(default_factory=list)
    pinned_models: dict[str, str] = Field(default_factory=dict)
    max_escalations: int | None = Field(default=None, ge=0, le=2)


def model_view(entry: ModelEntry) -> dict:
    return {
        "provider": entry.provider,
        "model_id": entry.model_id,
        "display_name": entry.display_name,
        "scope": "platform" if entry.scope == PLATFORM else "organization",
        "capabilities": entry.capabilities,
        "context_window": entry.context_window,
        "max_output_tokens": entry.max_output_tokens,
        "supports_tools": entry.supports_tools,
        "supports_structured_output": entry.supports_structured_output,
        "input_usd_per_mtok": entry.input_usd_per_mtok,
        "output_usd_per_mtok": entry.output_usd_per_mtok,
        "cached_input_usd_per_mtok": entry.cached_input_usd_per_mtok,
        "available": entry.available,
        "routable": entry.routable,
        "deprecated": entry.deprecated,
        "pricing_source": entry.pricing_source,
        "billing_model": "platform" if entry.scope == PLATFORM else "customer",
        "last_verified_at": entry.last_verified_at.isoformat(),
    }


async def routable_entries(db: AsyncSession, organization_id: uuid.UUID, settings: Settings) -> list[ModelEntry]:
    credentials = await credentials_for(db, organization_id, settings)
    entries = list(
        await db.scalars(select(ModelEntry).where(ModelEntry.scope.in_([PLATFORM, str(organization_id)])))
    )
    usable = []
    for entry in entries:
        if entry.provider == DEV_PROVIDER:
            if settings.mock_mode and not settings.is_production:
                usable.append(entry)
            continue
        credential = credentials.get(entry.provider)
        if credential and credential.scope == entry.scope:
            usable.append(entry)
    return usable


async def preferences(db: AsyncSession, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> RoutingPreference | None:
    for scope_id in ([str(project_id)] if project_id else []) + ["organization"]:
        found = await db.scalar(
            select(RoutingPreference).where(
                RoutingPreference.organization_id == organization_id, RoutingPreference.scope_id == scope_id
            )
        )
        if found:
            return found
    return None


def check_base_url(base_url: str, settings: Settings) -> None:
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Base URL must be an http(s) URL")
    if settings.is_production:
        if parsed.scheme != "https":
            raise HTTPException(status_code=422, detail="Base URL must use HTTPS")
        # Customer endpoints must not let the gateway reach internal services.
        for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443):
            address = ipaddress.ip_address(info[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise HTTPException(status_code=422, detail="Base URL resolves to a private address")


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/providers")
async def providers(
    identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[dict]:
    credentials = await credentials_for(db, identity.organization_id, settings)
    stored = {
        c.provider: c
        for c in await db.scalars(select(ProviderCredential).where(ProviderCredential.organization_id == identity.organization_id))
    }
    counts = dict(
        (
            await db.execute(
                select(ModelEntry.provider, func.count())
                .where(ModelEntry.scope.in_([PLATFORM, str(identity.organization_id)]), ModelEntry.available)
                .group_by(ModelEntry.provider)
            )
        ).all()
    )
    result = []
    for name, spec in PROVIDERS.items():
        credential = credentials.get(name)
        result.append(
            {
                "provider": name,
                "label": spec.label,
                "kind": spec.kind,
                "needs_key": spec.needs_key,
                "needs_base_url": spec.needs_base_url,
                "configured": credential.billing_model if credential else None,
                "key_fingerprint": stored[name].key_fingerprint if name in stored else None,
                "base_url": stored[name].base_url if name in stored else "",
                "models": counts.get(name, 0),
            }
        )
    if settings.mock_mode and not settings.is_production:
        result.append(
            {"provider": DEV_PROVIDER, "label": "Development model (no AI)", "kind": "development", "needs_key": False,
             "needs_base_url": False, "configured": "platform", "key_fingerprint": None, "base_url": "", "models": counts.get(DEV_PROVIDER, 0)}
        )
    return result


@app.put("/v1/credentials/{provider}")
async def put_credential(
    provider: str,
    body: CredentialInput,
    identity: Caller = Depends(admin_caller),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    spec = PROVIDERS.get(provider)
    if not spec:
        raise HTTPException(status_code=404, detail="Unknown provider")
    key = body.api_key.get_secret_value().strip() if body.api_key else ""
    if spec.needs_key and len(key) < 8:
        raise HTTPException(status_code=422, detail="An API key is required for this provider")
    if spec.needs_base_url and not body.base_url:
        raise HTTPException(status_code=422, detail="A base URL is required for this provider")
    check_base_url(body.base_url, settings)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            discovered = await discover(spec, key, body.base_url, client)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=400, detail=f"Provider rejected the credentials ({exc.response.status_code})") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail="Could not reach the provider") from exc
    stored = await db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == identity.organization_id, ProviderCredential.provider == provider
        )
    )
    stored = stored or ProviderCredential(organization_id=identity.organization_id, provider=provider, created_by=identity.user_id or uuid.uuid4())
    stored.encrypted_key = encrypt(key, settings) if key else ""
    stored.key_fingerprint = fingerprint(key) if key else ""
    stored.base_url = body.base_url
    db.add(stored)
    from .registry import upsert_models

    count = await upsert_models(db, provider, str(identity.organization_id), discovered, routable=True)
    await db.commit()
    return {"provider": provider, "configured": "customer", "models": count, "key_fingerprint": stored.key_fingerprint}


@app.delete("/v1/credentials/{provider}", status_code=204)
async def delete_credential(
    provider: str, identity: Caller = Depends(admin_caller), db: AsyncSession = Depends(get_db)
) -> Response:
    stored = await db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == identity.organization_id, ProviderCredential.provider == provider
        )
    )
    if not stored:
        raise HTTPException(status_code=404, detail="No stored credential")
    await db.delete(stored)
    for entry in await db.scalars(
        select(ModelEntry).where(ModelEntry.provider == provider, ModelEntry.scope == str(identity.organization_id))
    ):
        await db.delete(entry)
    await db.commit()
    return Response(status_code=204)


@app.post("/v1/registry/refresh")
async def refresh_registry(
    identity: Caller = Depends(admin_caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        return await refresh(db, identity.organization_id, settings, client)


@app.get("/v1/models")
async def list_models(
    provider: str | None = None,
    routable_only: bool = False,
    identity: Caller = Depends(caller),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if routable_only:
        entries = await routable_entries(db, identity.organization_id, settings)
    else:
        entries = list(await db.scalars(select(ModelEntry).where(ModelEntry.scope.in_([PLATFORM, str(identity.organization_id)]))))
    if provider:
        entries = [e for e in entries if e.provider == provider]
    return [model_view(e) for e in sorted(entries, key=lambda e: (e.provider, e.model_id))]


@app.get("/v1/tiers")
async def tiers(
    identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[dict]:
    entries = await routable_entries(db, identity.organization_id, settings)
    prefs = await preferences(db, identity.organization_id, identity.project_id)
    result = []
    for tier in TIERS:
        ordered = candidates(
            entries,
            RouteRequest(
                tier=tier,
                allowed_providers=prefs.allowed_providers if prefs else [],
                pinned_model=(prefs.pinned_models or {}).get(tier) if prefs else None,
            ),
            settings,
        )
        result.append({"tier": tier, "candidates": [model_view(e) for e in ordered[:5]], "count": len(ordered)})
    return result


@app.get("/v1/preferences")
async def get_preferences(identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    prefs = await preferences(db, identity.organization_id, identity.project_id)
    return {
        "scope": "project" if prefs and prefs.scope_id != "organization" else "organization",
        "default_tier": prefs.default_tier if prefs else "standard",
        "allowed_providers": prefs.allowed_providers if prefs else [],
        "pinned_models": prefs.pinned_models if prefs else {},
        "max_escalations": prefs.max_escalations if prefs and prefs.max_escalations is not None else settings.max_escalations,
        "max_attempts": settings.max_attempts,
    }


@app.put("/v1/preferences")
async def put_preferences(body: PreferenceInput, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)) -> dict:
    scope_id = str(identity.project_id) if identity.project_id else "organization"
    if scope_id == "organization" and identity.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Administrator role required")
    unknown = [p for p in body.allowed_providers if p not in PROVIDERS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown providers: {', '.join(unknown)}")
    prefs = await db.scalar(
        select(RoutingPreference).where(RoutingPreference.organization_id == identity.organization_id, RoutingPreference.scope_id == scope_id)
    ) or RoutingPreference(organization_id=identity.organization_id, scope_id=scope_id)
    prefs.default_tier = body.default_tier
    prefs.allowed_providers = body.allowed_providers
    prefs.pinned_models = body.pinned_models
    prefs.max_escalations = body.max_escalations
    db.add(prefs)
    await db.commit()
    return {"scope": "project" if identity.project_id else "organization", **body.model_dump()}


@app.put("/v1/budgets")
async def put_budget(
    body: BudgetInput, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    if body.scope == "organization_monthly":
        if identity.role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Administrator role required")
        scope_id = str(identity.organization_id)
    else:
        if not identity.project_id:
            raise HTTPException(status_code=422, detail="Project budgets require a project-scoped token")
        scope_id = str(identity.project_id)
    budget = await budget_service.get_or_default(db, identity.organization_id, body.scope, scope_id, settings)
    budget.limit_usd = body.limit_usd
    budget.hard_limit = body.hard_limit
    budget.alert_threshold = body.alert_threshold
    await db.commit()
    return {"scope": body.scope, "limit_usd": budget.limit_usd, "hard_limit": budget.hard_limit, "alert_threshold": budget.alert_threshold}


async def _record(db: AsyncSession, identity: Caller, request_id: str, entry: ModelEntry, tier: str, billing_model: str,
                  status: str, attempt: int, agent: str, started: float, completion=None, error: str | None = None,
                  attribution: ChatRequest | None = None) -> UsageRecord:
    record = UsageRecord(
        task_id=attribution.task_id if attribution else None,
        execution_id=attribution.execution_id if attribution else None,
        strategy=attribution.strategy if attribution else None,
        request_id=request_id,
        organization_id=identity.organization_id,
        user_id=identity.user_id,
        project_id=identity.project_id,
        agent=agent,
        provider=entry.provider,
        model_id=entry.model_id,
        tier=tier,
        billing_model=billing_model,
        status=status,
        attempt=attempt,
        input_tokens=completion.input_tokens if completion else 0,
        output_tokens=completion.output_tokens if completion else 0,
        cached_tokens=completion.cached_tokens if completion else 0,
        cost_usd=cost(entry, completion) if completion else 0,
        latency_ms=int((time.monotonic() - started) * 1000),
        error=error,
    )
    db.add(record)
    await db.flush()
    return record


@app.post("/v1/chat")
async def chat(
    body: ChatRequest, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    request_id = body.request_id or uuid.uuid4().hex
    if request_id in INFLIGHT:
        raise HTTPException(status_code=409, detail="A request with this id is already running")
    prefs = await preferences(db, identity.organization_id, identity.project_id)
    tier = body.tier or (COMPLEXITY_TIER[body.complexity] if body.complexity else None) or (prefs.default_tier if prefs else "standard")
    max_escalations = prefs.max_escalations if prefs and prefs.max_escalations is not None else settings.max_escalations
    max_output = body.max_output_tokens or settings.default_max_output_tokens

    budget_states = await budget_service.states(db, identity.organization_id, identity.project_id, settings)
    remaining = budget_service.remaining(budget_states, body.task_budget_usd or settings.default_task_budget_usd)
    if remaining <= 0:
        await budget_service.record_alerts(db, budget_states)
        await db.commit()
        raise HTTPException(status_code=402, detail="Budget exhausted. Raise the limit in usage settings to continue.")

    messages = [m.model_dump() for m in body.messages]
    estimated_input = estimate_tokens(messages)
    entries = await routable_entries(db, identity.organization_id, settings)
    credentials = await credentials_for(db, identity.organization_id, settings)
    if body.model:
        return await _pinned_chat(db, identity, body, request_id, entries, credentials, messages, estimated_input, max_output,
                                  remaining, settings)
    attempts: list[dict] = []
    tried: set[str] = set()
    blocked_providers: set[str] = set()
    considered = 0

    for current_tier in escalation_path(tier, max_escalations):
        ordered = candidates(
            entries,
            RouteRequest(
                tier=current_tier,
                capabilities=body.capabilities,
                estimated_input_tokens=estimated_input,
                max_output_tokens=max_output,
                allowed_providers=prefs.allowed_providers if prefs else [],
                pinned_model=(prefs.pinned_models or {}).get(current_tier) if prefs else None,
                remaining_budget_usd=remaining,
            ),
            settings,
        )
        considered += len(ordered)
        for entry in ordered:
            key = f"{entry.provider}/{entry.model_id}"
            if key in tried or entry.provider in blocked_providers:
                continue
            if len(attempts) >= settings.max_attempts:
                break
            tried.add(key)
            credential = credentials.get(entry.provider)
            billing_model = credential.billing_model if credential else "platform"
            started = time.monotonic()
            task = asyncio.create_task(
                complete(entry, credential, messages, max_output, settings.request_timeout_seconds, body.response_format)
            )
            INFLIGHT[request_id] = (identity.organization_id, task)
            try:
                completion = await task
            except asyncio.CancelledError:
                await _record(db, identity, request_id, entry, current_tier, billing_model, "cancelled", len(attempts) + 1, body.agent, started, attribution=body)
                await db.commit()
                raise HTTPException(status_code=499, detail="Request cancelled") from None
            except ProviderError as exc:
                await _record(db, identity, request_id, entry, current_tier, billing_model, "failed", len(attempts) + 1, body.agent, started, error=exc.kind, attribution=body)
                attempts.append({"model": key, "tier": current_tier, "status": "failed", "error": exc.kind})
                if exc.kind in {"authentication", "rate_limited", "no_credentials"}:
                    blocked_providers.add(entry.provider)
                continue
            finally:
                INFLIGHT.pop(request_id, None)
            record = await _record(db, identity, request_id, entry, current_tier, billing_model, "succeeded", len(attempts) + 1, body.agent, started, completion, attribution=body)
            attempts.append({"model": key, "tier": current_tier, "status": "succeeded"})
            alerts = await budget_service.record_alerts(
                db, await budget_service.states(db, identity.organization_id, identity.project_id, settings)
            )
            await db.commit()
            return {
                "request_id": request_id,
                "content": completion.content,
                "provider": entry.provider,
                "model_id": entry.model_id,
                "display_name": entry.display_name,
                "tier": current_tier,
                "requested_tier": tier,
                "billing_model": billing_model,
                "development_model": entry.provider == DEV_PROVIDER,
                "usage": {
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "cached_tokens": record.cached_tokens,
                    "cost_usd": record.cost_usd,
                    "latency_ms": record.latency_ms,
                },
                "attempts": attempts,
                "alerts": alerts,
            }
        if len(attempts) >= settings.max_attempts:
            break
    await db.commit()
    if not considered:
        raise HTTPException(
            status_code=422,
            detail="No configured model satisfies this request's tier, capabilities, context size, and remaining budget.",
        )
    raise HTTPException(status_code=502, detail={"message": "All model attempts failed", "attempts": attempts})


async def _pinned_chat(db: AsyncSession, identity: Caller, body: ChatRequest, request_id: str, entries: list[ModelEntry], credentials: dict,
                       messages: list[dict], estimated_input: int, max_output: int, remaining: float, settings: Settings) -> dict:
    entry = next((e for e in entries if f"{e.provider}/{e.model_id}" == body.model and e.available and e.routable and not e.deprecated), None)
    if not entry:
        raise HTTPException(status_code=422, detail="The pinned model is not routable for this organization")
    if (entry.context_window or DEFAULT_CONTEXT) < estimated_input + max_output and entry.provider != DEV_PROVIDER:
        raise HTTPException(status_code=422, detail="Request exceeds the pinned model's context window")
    if worst_case_cost(entry, estimated_input, max_output) > remaining:
        raise HTTPException(status_code=402, detail="The request's worst-case cost exceeds the remaining budget")
    credential = credentials.get(entry.provider)
    billing_model = credential.billing_model if credential else "platform"
    tier = body.strategy or "pinned"
    started = time.monotonic()
    task = asyncio.create_task(complete(entry, credential, messages, max_output, settings.request_timeout_seconds, body.response_format))
    INFLIGHT[request_id] = (identity.organization_id, task)
    try:
        completion = await task
    except asyncio.CancelledError:
        await _record(db, identity, request_id, entry, tier, billing_model, "cancelled", 1, body.agent, started, attribution=body)
        await db.commit()
        raise HTTPException(status_code=499, detail="Request cancelled") from None
    except ProviderError as exc:
        await _record(db, identity, request_id, entry, tier, billing_model, "failed", 1, body.agent, started, error=exc.kind, attribution=body)
        await db.commit()
        raise HTTPException(status_code=502, detail={"message": f"Model call failed: {exc.kind}", "error": exc.kind}) from None
    finally:
        INFLIGHT.pop(request_id, None)
    record = await _record(db, identity, request_id, entry, tier, billing_model, "succeeded", 1, body.agent, started, completion, attribution=body)
    alerts = await budget_service.record_alerts(db, await budget_service.states(db, identity.organization_id, identity.project_id, settings))
    await db.commit()
    return {
        "request_id": request_id, "content": completion.content, "provider": entry.provider, "model_id": entry.model_id,
        "display_name": entry.display_name, "tier": tier, "requested_tier": tier, "billing_model": billing_model,
        "development_model": entry.provider == DEV_PROVIDER,
        "usage": {"input_tokens": record.input_tokens, "output_tokens": record.output_tokens, "cached_tokens": record.cached_tokens,
                  "cost_usd": record.cost_usd, "latency_ms": record.latency_ms},
        "attempts": [{"model": body.model, "tier": tier, "status": "succeeded"}], "alerts": alerts,
    }


@app.get("/v1/budgets")
async def get_budgets(identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    budget_states = await budget_service.states(db, identity.organization_id, identity.project_id, settings)
    await db.commit()
    return {
        "budgets": [
            {"scope": s.budget.scope, "scope_id": s.budget.scope_id, "limit_usd": s.budget.limit_usd, "spent_usd": round(s.spent_usd, 8),
             "remaining_usd": round(s.remaining_usd, 8), "hard_limit": s.budget.hard_limit, "alert_threshold": s.budget.alert_threshold}
            for s in budget_states
        ]
    }


@app.post("/v1/requests/{request_id}/cancel")
async def cancel(request_id: str, identity: Caller = Depends(caller)) -> dict:
    inflight = INFLIGHT.get(request_id)
    if not inflight or inflight[0] != identity.organization_id:
        raise HTTPException(status_code=404, detail="No running request with this id")
    inflight[1].cancel()
    return {"request_id": request_id, "status": "cancelling"}


@app.get("/v1/usage")
async def usage(
    identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    base = select(UsageRecord).where(UsageRecord.organization_id == identity.organization_id)
    if identity.project_id:
        base = base.where(UsageRecord.project_id == identity.project_id)
    records = list(await db.scalars(base.order_by(UsageRecord.created_at.desc()).limit(2000)))

    def group(key) -> list[dict]:
        buckets: dict[str, dict] = {}
        for r in records:
            name = key(r)
            bucket = buckets.setdefault(name, {"key": name, "requests": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0})
            bucket["requests"] += 1
            bucket["failed"] += r.status != "succeeded"
            bucket["input_tokens"] += r.input_tokens
            bucket["output_tokens"] += r.output_tokens
            bucket["cached_tokens"] += r.cached_tokens
            bucket["cost_usd"] = round(bucket["cost_usd"] + r.cost_usd, 8)
        return sorted(buckets.values(), key=lambda b: -b["cost_usd"])

    totals = group(lambda _: "total")
    budget_states = await budget_service.states(db, identity.organization_id, identity.project_id, settings)
    await db.commit()
    alerts = list(
        await db.scalars(
            select(BudgetAlert).where(BudgetAlert.organization_id == identity.organization_id).order_by(BudgetAlert.created_at.desc()).limit(10)
        )
    )
    return {
        "totals": totals[0] if totals else {"key": "total", "requests": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0},
        "failed_cost_usd": round(sum(r.cost_usd for r in records if r.status != "succeeded"), 8),
        "by_model": group(lambda r: f"{r.provider}/{r.model_id}"),
        "by_agent": group(lambda r: r.agent),
        "by_project": group(lambda r: str(r.project_id) if r.project_id else "none"),
        "by_user": group(lambda r: str(r.user_id) if r.user_id else "service"),
        "by_billing_model": group(lambda r: r.billing_model),
        "budgets": [
            {
                "scope": s.budget.scope,
                "limit_usd": s.budget.limit_usd,
                "spent_usd": round(s.spent_usd, 8),
                "remaining_usd": round(s.remaining_usd, 8),
                "hard_limit": s.budget.hard_limit,
                "alert_threshold": s.budget.alert_threshold,
            }
            for s in budget_states
        ],
        "alerts": [{"message": a.message, "kind": a.kind, "created_at": a.created_at.isoformat()} for a in alerts],
        "recent": [
            {
                "request_id": r.request_id, "agent": r.agent, "model": f"{r.provider}/{r.model_id}", "tier": r.tier,
                "status": r.status, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                "cost_usd": r.cost_usd, "latency_ms": r.latency_ms, "created_at": r.created_at.isoformat(),
            }
            for r in records[:20]
        ],
    }

