import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import ProjectEnvVar
from app.schemas import Principal
from app.security import DEV_ORG_ID, get_principal
from app.services import gateway as gateway_client

GATEWAY_DIR = Path(__file__).resolve().parents[2] / "services" / "model-gateway"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def as_user(role: str = "member", org: uuid.UUID = DEV_ORG_ID) -> Principal:
    principal = Principal(user_id=uuid.uuid4(), organization_id=org, email=f"{role}@example.com", role=role)
    app.dependency_overrides[get_principal] = lambda: principal
    return principal


def create(client: TestClient, prompt: str) -> dict:
    response = client.post("/api/v1/projects", json={"prompt": prompt})
    assert response.status_code == 201, response.text
    return response.json()


def test_project_creation_derives_name_template_and_dashboard_fields(client):
    project = create(client, 'Build a property management app called "Keyhold" with tenants, rent, and mobile apps for tenants')
    assert project["name"] == "Keyhold"
    assert project["template"] == "full-stack"
    assert project["generation_status"] == "draft"
    assert project["deployment_status"] == "not_deployed"
    assert project["estimated_usage_usd"] == 0
    assert "FastAPI" in project["stack"]
    listed = client.get("/api/v1/projects").json()
    assert project["id"] in [p["id"] for p in listed]
    simple = create(client, "A landing page for my bakery")
    assert simple["template"] == "react-web"


def test_projects_are_isolated_between_tenants_and_members(client):
    project = create(client, "An internal tool for tracking equipment loans")
    as_user("owner", org=uuid.uuid4())
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert project["id"] not in [p["id"] for p in client.get("/api/v1/projects").json()]
    as_user("member")
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert client.post(f"/api/v1/projects/{project['id']}/messages", json={"content": "hi"}).status_code == 404


def test_viewers_are_read_only(client):
    as_user("viewer")
    assert client.post("/api/v1/projects", json={"prompt": "Viewer project attempt"}).status_code == 403


def test_environment_values_are_write_only_and_encrypted(client):
    project = create(client, "A billing portal with Stripe")
    put = client.put(
        f"/api/v1/projects/{project['id']}/env",
        json={"key": "STRIPE_SECRET_KEY", "value": "sk_test_value_never_returned", "environment": "development"},
    )
    assert put.status_code == 200
    listed = client.get(f"/api/v1/projects/{project['id']}/env").json()
    assert listed == [{"key": "STRIPE_SECRET_KEY", "environment": "development", "updated_at": listed[0]["updated_at"]}]
    assert "sk_test_value_never_returned" not in str(listed)

    async def stored() -> str:
        async with SessionLocal() as db:
            row = await db.scalar(select(ProjectEnvVar).where(ProjectEnvVar.project_id == uuid.UUID(project["id"])))
            return row.encrypted_value

    assert "sk_test_value_never_returned" not in asyncio.run(stored())
    bad = client.put(f"/api/v1/projects/{project['id']}/env", json={"key": "lower-case", "value": "x"})
    assert bad.status_code == 422


def test_project_deletion_requires_typed_confirmation(client):
    project = create(client, 'A recipe sharing site called "Pantry"')
    assert client.delete(f"/api/v1/projects/{project['id']}", params={"confirm_name": "wrong"}).status_code == 422
    assert client.delete(f"/api/v1/projects/{project['id']}", params={"confirm_name": "Pantry"}).status_code == 204
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404


def test_gateway_tokens_are_scoped_and_short_lived():
    import jwt

    from app.config import get_settings

    principal = Principal(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), email="a@b.c", role="member")
    project_id = uuid.uuid4()
    claims = jwt.decode(
        gateway_client.service_token(get_settings(), principal, project_id),
        gateway_client.DEV_GATEWAY_SECRET,
        algorithms=["HS256"],
        audience=gateway_client.AUDIENCE,
    )
    assert claims["org"] == str(principal.organization_id)
    assert claims["project"] == str(project_id)
    assert claims["exp"] - claims["iat"] <= 180


@pytest.fixture
def live_gateway(monkeypatch):
    """Run the real model gateway in-process so the service-token handshake is exercised."""
    database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    os.environ["GATEWAY_DATABASE_URL"] = f"sqlite+aiosqlite:///{database.name}"
    os.environ["GATEWAY_OPENROUTER_PUBLIC_CATALOG"] = "false"
    sys.path.insert(0, str(GATEWAY_DIR))
    from gateway.database import SessionLocal as GatewaySession
    from gateway.database import engine as gateway_engine
    from gateway.main import app as gateway_app
    from gateway.models import Base as GatewayBase
    from gateway.registry import seed_dev_models

    async def prepare():
        async with gateway_engine.begin() as connection:
            await connection.run_sync(GatewayBase.metadata.create_all)
        async with GatewaySession() as db:
            from gateway.config import get_settings as gateway_settings

            await seed_dev_models(db, gateway_settings())
        await gateway_engine.dispose()

    asyncio.run(prepare())
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.ASGITransport(app=gateway_app)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(gateway_client.httpx, "AsyncClient", client_factory)
    yield
    sys.path.remove(str(GATEWAY_DIR))


def test_chat_goes_through_the_model_gateway_and_records_cost(client, live_gateway):
    project = create(client, "A maintenance request tracker for landlords")
    response = client.post(f"/api/v1/projects/{project['id']}/messages", json={"content": project["prompt"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant_message"]["development_model"] is True
    assert body["assistant_message"]["model"] == "omniweb_dev/dev-fast"
    messages = client.get(f"/api/v1/projects/{project['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    executions = client.get(f"/api/v1/projects/{project['id']}/executions").json()
    assert executions[0]["status"] == "succeeded" and executions[0]["agent"] == "requirements"
    usage = client.get(f"/api/v1/projects/{project['id']}/usage").json()
    assert usage["totals"]["requests"] == 1
    assert client.get(f"/api/v1/projects/{project['id']}").json()["generation_status"] == "planning"
    providers = client.get("/api/v1/ai/providers").json()
    assert {"openai", "anthropic", "gemini", "openrouter", "openai_compatible", "ollama"} <= {p["provider"] for p in providers}
