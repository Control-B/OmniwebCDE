"""The control plane driving AAEE in-process, with AAEE's mocked gateway (no paid inference)."""

import asyncio
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.builder import pipeline
from app.builder.store import ProjectStore
from app.config import get_settings
from app.database import SessionLocal
from app.database import engine as api_engine
from app.models import AgentExecution, GenerationRun, Project
from app.services import aaee as aaee_client

AAEE_DIR = Path(__file__).resolve().parents[2] / "services" / "ai-execution-engine"
PROMPT = "A tool library where neighbours lend ladders and drills"


class Bridge(httpx.AsyncBaseTransport):
    """Forwards async requests to AAEE's TestClient, which runs AAEE (and its background
    workers) on its own event loop with its lifespan started."""

    def __init__(self, client):
        self.client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        url = request.url.raw_path.decode()
        response = await asyncio.to_thread(
            self.client.request, request.method, url, content=body, headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )


@pytest.fixture
def live_aaee(monkeypatch):
    sys.path.insert(0, str(AAEE_DIR))
    spec = importlib.util.spec_from_file_location(
        "aaee_fixtures", AAEE_DIR / "tests" / "conftest.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    from aaee.main import app as aaee_app
    from aaee.model_registry import Registry
    from fastapi.testclient import TestClient

    fake = fixtures.FakeGateway()
    aaee_app.state.gateway = fake
    aaee_app.state.registry = Registry(fake, 0)
    with TestClient(aaee_app) as engine_client:
        monkeypatch.setattr(
            aaee_client,
            "http_client",
            lambda settings, timeout: httpx.AsyncClient(
                transport=Bridge(engine_client), base_url="http://aaee"
            ),
        )
        yield fake, engine_client
    sys.path.remove(str(AAEE_DIR))


def make_run(client) -> tuple[dict, dict]:
    project = client.post("/api/v1/projects", json={"prompt": PROMPT}).json()

    async def create():
        await api_engine.dispose()
        async with SessionLocal() as db:
            row = await db.get(Project, uuid.UUID(project["id"]))
            run = GenerationRun(
                project_id=row.id,
                organization_id=row.organization_id,
                requested_by=row.owner_id,
                kind="edit",
                status="running",
            )
            db.add(run)
            await db.commit()
            return str(run.id)

    run_id = asyncio.run(create())
    return project, {
        "run_id": run_id,
        "project_id": project["id"],
        "kind": "edit",
        "resume_at": "understand",
    }


PASSING = {
    "ok": True,
    "steps": [
        {
            "name": "web.typecheck",
            "label": "Type-check",
            "target": "web",
            "ok": True,
            "duration": 1.0,
            "output": "",
        },
        {
            "name": "web.build",
            "label": "Build",
            "target": "web",
            "ok": True,
            "duration": 2.0,
            "output": "",
        },
    ],
}
FAILING = {
    "ok": False,
    "steps": [
        {
            "name": "web.typecheck",
            "label": "Type-check",
            "target": "web",
            "ok": False,
            "duration": 1.0,
            "output": "apps/web/src/App.tsx(1,1): error TS2304",
        }
    ],
}


def test_rule_based_edits_cost_nothing_and_are_validated(client, live_aaee):
    fake, engine_client = live_aaee
    project, state = make_run(client)

    async def flow():
        await api_engine.dispose()
        store = ProjectStore(get_settings(), project["id"])
        await store.init("main")
        store.write("apps/web/src/theme.ts", "export const accent = 'green'\n")
        result = await pipeline.ask_model(
            state,
            "editor",
            "system",
            "make it green",
            engine_task={
                "deterministic_options": [{"tool": "builder.spec_rules", "coverage": "exact"}]
            },
        )
        assert result["deterministic"] == "builder.spec_rules" and fake.calls == []
        pending = [{**result["aaee"], "files": ["apps/web/src/theme.ts"]}]
        assert await pipeline.report_checks(state, pending, PASSING, continue_repair=False) is None
        async with SessionLocal() as db:
            row = await db.scalar(
                select(AgentExecution).where(
                    AgentExecution.aaee_task_id == result["aaee"]["task_id"]
                )
            )
            return result["aaee"]["task_id"], row

    task_id, row = asyncio.run(flow())
    assert row.strategy == "deterministic" and row.phase == "implementation" and row.cost_usd == 0
    task = client.get(f"/api/v1/ai/tasks/{task_id}").json()
    assert task["status"] == "completed" and task["total_cost_usd"] == 0
    listed = client.get("/api/v1/ai/tasks", params={"project_id": project["id"]}).json()
    assert [t["id"] for t in listed] == [task_id]


def test_failed_repair_is_escalated_by_aaee_and_learned_from(client, live_aaee):
    fake, engine_client = live_aaee
    project, state = make_run(client)
    first = {
        "files": [{"path": "apps/web/src/App.tsx", "content": "export const App = () => null\n"}],
        "summary": "v1",
    }
    second = {
        "files": [
            {"path": "apps/web/src/App.tsx", "content": "export const App = () => <main />\n"}
        ],
        "summary": "v2",
    }

    async def flow():
        await api_engine.dispose()
        store = ProjectStore(get_settings(), project["id"])
        await store.init("main")
        fake.default_response = json.dumps(first)
        result = await pipeline.ask_model(
            state,
            "repair",
            "system",
            "fix it",
            engine_task={
                "engine_prompt": False,
                "description": "Fix the failing type-check",
                "input_artifacts": [
                    {"path": "apps/web/src/App.tsx", "content": "export const App = () => nul\n"}
                ],
                "allowed_paths": ["apps/web/src/"],
                "maximum_attempts": 2,
            },
        )
        assert result["files"] == {"apps/web/src/App.tsx": first["files"][0]["content"]}
        first_model = fake.calls[-1]["model"]
        for path, content in result["files"].items():
            store.write(path, content)
        fake.default_response = json.dumps(second)
        proposal = await pipeline.report_checks(
            state,
            [{**result["aaee"], "files": list(result["files"])}],
            FAILING,
            continue_repair=True,
        )
        assert (
            proposal["aaee"]["task_id"] == result["aaee"]["task_id"]
            and proposal["aaee"]["execution_id"] != result["aaee"]["execution_id"]
        )
        escalated_model = fake.calls[-1]["model"]
        for path, content in proposal["files"].items():
            store.write(path, content)
        assert (
            await pipeline.report_checks(
                state,
                [{**proposal["aaee"], "files": list(proposal["files"])}],
                PASSING,
                continue_repair=True,
            )
            is None
        )
        return result["aaee"]["task_id"], first_model, escalated_model

    task_id, first_model, escalated_model = asyncio.run(flow())
    assert first_model != escalated_model
    task = client.get(f"/api/v1/ai/tasks/{task_id}").json()
    assert task["status"] == "completed" and task["development_phase"] == "debugging"
    assert [e["validation"] for e in task["executions"]] == ["failed", "passed"]
    analytics = client.get("/api/v1/ai/admin/analytics").json()
    assert analytics["summary"]["completed"] >= 1 and analytics["summary"]["retry_cost_usd"] > 0


def test_cde_agent_tasks_propose_edits_and_learn_from_user_checks(client, live_aaee):
    fake, engine_client = live_aaee
    connection = client.post(
        "/api/v1/cloud-connections", json={"label": "Agent DO", "token": "dop_v1_mock_token"}
    ).json()
    workspace = client.post(
        "/api/v1/workspaces",
        json={
            "name": f"agent-{uuid.uuid4().hex[:6]}",
            "cloud_connection_id": connection["id"],
            "region": "nyc3",
            "size": "s-2vcpu-4gb",
            "idempotency_key": uuid.uuid4().hex,
            "approved_estimated_monthly_usd": "24.00",
        },
    )
    assert workspace.status_code == 201, workspace.text
    base = f"/api/v1/workspaces/{workspace.json()['id']}/agent-tasks"
    fake.default_response = json.dumps(
        {
            "files": [
                {
                    "path": "src/math.ts",
                    "content": "export const add = (a: number, b: number) => a + b\n",
                }
            ],
            "summary": "Fixed add",
        }
    )
    created = client.post(
        base,
        json={
            "instruction": "Fix add so it returns the sum",
            "task_type": "debugging",
            "files": [{"path": "src/math.ts", "content": "export const add = (a, b) => a - b\n"}],
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert (
        task["status"] == "awaiting_validation"
        and task["proposal"]["files"][0]["path"] == "src/math.ts"
        and task["phase"] == "debugging"
    )
    reported = client.post(
        f"{base}/{task['id']}/checks",
        json={"items": [{"name": "npm test", "kind": "unit_tests", "status": "passed"}]},
    ).json()
    assert reported["status"] == "completed"
    assert client.get(base).json()[0]["id"] == task["id"]

    other = client.post(
        base, json={"instruction": "Leak the deploy key", "task_type": "documentation"}
    ).json()
    discarded = client.post(f"{base}/{other['id']}/discard").json()
    assert discarded["status"] in {"cancelled", "completed"}


def test_engine_access_flags_and_member_scoping(client, live_aaee):
    from app.main import app
    from app.schemas import Principal
    from app.security import DEV_ORG_ID, get_principal

    access = client.get("/api/v1/ai/engine").json()
    assert access == {"available": True, "tenant_admin": True, "platform_admin": True}
    member = Principal(
        user_id=uuid.uuid4(),
        organization_id=DEV_ORG_ID,
        email="m@example.com",
        role="member",
        auth_mode="oidc",
    )
    app.dependency_overrides[get_principal] = lambda: member
    assert client.get("/api/v1/ai/tasks").status_code == 403
    assert client.get("/api/v1/ai/admin/analytics").status_code == 403
    assert client.get("/api/v1/ai/engine").json()["platform_admin"] is False
    app.dependency_overrides.clear()
