import asyncio
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from gateway import main
from gateway.config import get_settings
from gateway.database import SessionLocal, engine
from gateway.inference import Completion, ProviderError
from gateway.main import app
from gateway.models import Base, ModelEntry, ProviderCredential, UsageRecord
from gateway.providers import DiscoveredModel

from .conftest import headers

CHAT = {"messages": [{"role": "user", "content": "Build a property management app"}], "agent": "requirements"}


def test_service_token_is_required():
    with TestClient(app) as client:
        assert client.get("/v1/models").status_code == 401
        assert client.get("/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_development_model_answers_and_records_usage(org):
    project = uuid.uuid4()
    with TestClient(app) as client:
        response = client.post("/v1/chat", json=CHAT, headers=headers(org, user=uuid.uuid4(), project=project))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["development_model"] is True
        assert body["usage"]["cost_usd"] == 0
        assert "no AI provider is configured" in body["content"]
        usage = client.get("/v1/usage", headers=headers(org, project=project)).json()
        assert usage["totals"]["requests"] == 1
        assert usage["by_agent"][0]["key"] == "requirements"
        assert {b["scope"] for b in usage["budgets"]} == {"organization_monthly", "project"}


def test_usage_is_isolated_per_organization(org):
    with TestClient(app) as client:
        client.post("/v1/chat", json=CHAT, headers=headers(org))
        other = client.get("/v1/usage", headers=headers(uuid.uuid4())).json()
        assert other["totals"]["requests"] == 0


def test_hard_budget_blocks_requests(org):
    with TestClient(app) as client:
        set_budget = client.put("/v1/budgets", json={"scope": "organization_monthly", "limit_usd": 0}, headers=headers(org))
        assert set_budget.status_code == 200
        assert client.post("/v1/chat", json=CHAT, headers=headers(org)).status_code == 402


def test_members_cannot_change_org_budget_or_keys(org):
    with TestClient(app) as client:
        member = headers(org, role="member")
        assert client.put("/v1/budgets", json={"scope": "organization_monthly", "limit_usd": 999}, headers=member).status_code == 403
        assert client.put("/v1/credentials/openai", json={"api_key": "sk-member-attempt"}, headers=member).status_code == 403


async def _seed_openai_models(names: list[tuple[str, float]]) -> None:
    async with SessionLocal() as db:
        for name, price in names:
            exists = await db.scalar(select(ModelEntry).where(ModelEntry.model_id == name))
            if not exists:
                db.add(ModelEntry(provider="openai", model_id=name, scope="platform", capabilities=[], context_window=128_000,
                                  input_usd_per_mtok=price, output_usd_per_mtok=price * 4, pricing_source="test"))
        await db.commit()


def test_fallback_records_failures_and_bounds_attempts(org, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-platform-key")
    calls: list[str] = []

    async def fake_complete(entry, credential, messages, max_output, timeout, response_format=None):
        calls.append(entry.model_id)
        if entry.model_id == "flaky-model":
            raise ProviderError("provider_error", "boom")
        return Completion("ok", 1000, 500, 200)

    monkeypatch.setattr(main, "complete", fake_complete)
    with TestClient(app) as client:
        asyncio.run(_seed_openai_models([("flaky-model", 2.0), ("steady-model", 1.0)]))
        response = client.post("/v1/chat", json={**CHAT, "tier": "standard"}, headers=headers(org))
        assert response.status_code == 200, response.text
        body = response.json()
        assert [a["status"] for a in body["attempts"]] == ["failed", "succeeded"]
        assert body["model_id"] == "steady-model" and body["billing_model"] == "platform"
        # 800 uncached input at $1, 200 cached at $1 (no cached price), 500 output at $4 per million tokens.
        assert body["usage"]["cost_usd"] == pytest.approx((800 * 1 + 200 * 1 + 500 * 4) / 1_000_000)
        usage = client.get("/v1/usage", headers=headers(org)).json()
        assert usage["totals"]["requests"] == 2 and usage["totals"]["failed"] == 1

        async def always_fail(*args, **kwargs):
            raise ProviderError("provider_error", "down")

        monkeypatch.setattr(main, "complete", always_fail)
        monkeypatch.setattr(settings, "max_attempts", 2)
        failed = client.post("/v1/chat", json={**CHAT, "tier": "standard"}, headers=headers(org))
        assert failed.status_code == 502
        assert len(failed.json()["detail"]["attempts"]) == 2


def test_customer_keys_are_verified_encrypted_and_take_precedence(org, monkeypatch):
    async def fake_discover(spec, api_key, base_url, client):
        assert api_key == "sk-customer-secret-123"
        return [DiscoveredModel(model_id="customer-model", input_usd_per_mtok=0.2, output_usd_per_mtok=0.8, pricing_source="test")]

    monkeypatch.setattr(main, "discover", fake_discover)
    with TestClient(app) as client:
        stored = client.put("/v1/credentials/openai", json={"api_key": "sk-customer-secret-123"}, headers=headers(org))
        assert stored.status_code == 200, stored.text
        assert stored.json()["configured"] == "customer"
        providers = {p["provider"]: p for p in client.get("/v1/providers", headers=headers(org)).json()}
        assert providers["openai"]["configured"] == "customer"
        assert "sk-customer" not in str(providers)

        async def raw_key() -> str:
            async with SessionLocal() as db:
                row = await db.scalar(select(ProviderCredential).where(ProviderCredential.organization_id == org))
                return row.encrypted_key

        assert "sk-customer-secret-123" not in asyncio.run(raw_key())

        monkeypatch.setattr(main, "complete", lambda *a, **k: _done())
        body = client.post("/v1/chat", json={**CHAT, "tier": "economy"}, headers=headers(org)).json()
        assert body["model_id"] == "customer-model" and body["billing_model"] == "customer"
        other_org = client.get("/v1/models?routable_only=true", headers=headers(uuid.uuid4())).json()
        assert "customer-model" not in [m["model_id"] for m in other_org]


async def _done() -> Completion:
    return Completion("customer reply", 10, 10, 0)


async def test_running_requests_can_be_cancelled(org, monkeypatch):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await main.seed_dev_models(db, get_settings())
    started = asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(main, "complete", slow)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        pending = asyncio.create_task(
            client.post("/v1/chat", json={**CHAT, "request_id": "cancel-me-123"}, headers=headers(org))
        )
        await asyncio.wait_for(started.wait(), 5)
        assert (await client.post("/v1/requests/cancel-me-123/cancel", headers=headers(uuid.uuid4()))).status_code == 404
        assert (await client.post("/v1/requests/cancel-me-123/cancel", headers=headers(org))).status_code == 200
        response = await asyncio.wait_for(pending, 5)
        assert response.status_code == 499
    async with SessionLocal() as db:
        record = await db.scalar(select(UsageRecord).where(UsageRecord.request_id == "cancel-me-123"))
        assert record.status == "cancelled"
    await engine.dispose()
