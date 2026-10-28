"""End-to-end engine scenarios through the API, with a mocked gateway (no paid inference)."""

import asyncio
import json
import uuid

from sqlalchemy import select

from aaee.database import SessionLocal
from aaee.inference_gateway import GatewayError
from aaee.models import BudgetCounter, BudgetReservation, Execution, RoutingPolicy, UsageEvent

from .conftest import headers

FILES_OK = json.dumps({"files": [{"path": "src/Pricing.tsx", "content": "export const Pricing = () => null\n"}], "summary": "Added page"})
FILES_V2 = json.dumps({"files": [{"path": "src/Pricing.tsx", "content": "export const Pricing = () => <main />\n"}], "summary": "v2"})
PASS = [{"name": "web.typecheck", "kind": "typecheck", "status": "passed"}, {"name": "web.build", "kind": "build", "status": "passed"}]
TYPE_FAIL = [
    {"name": "web.typecheck", "kind": "typecheck", "status": "failed", "output": "src/Pricing.tsx:1:1 error TS2322: Type 'x' is not assignable"},
    {"name": "web.build", "kind": "build", "status": "passed"},
]


def submit(client, org, body, **identity):
    response = client.post("/v1/tasks?wait=10", json=body, headers=headers(org, **identity))
    assert response.status_code == 201, response.text
    return response.json()


def frontend(**extra):
    return {
        "task_type": "frontend_generation",
        "task_description": "Build a pricing page",
        "allowed_paths": ["src/"],
        "execution_environment": {"kind": "builder_sandbox"},
        "project_id": str(uuid.uuid4()),
        **extra,
    }


def validate(client, org, task, items, **extra):
    action = task["next_action"]
    response = client.post(
        f"/v1/tasks/{task['id']}/validation?", json={"execution_id": action["execution_id"], "report": {"items": items, **extra}}, headers=headers(org)
    )
    assert response.status_code == 200, response.text
    return response.json()


def settle(client, org, task_id, statuses=("queued", "running")):
    for _ in range(200):
        task = client.get(f"/v1/tasks/{task_id}", headers=headers(org)).json()
        if task["status"] not in statuses:
            return task
        asyncio.run(asyncio.sleep(0.02))
    raise AssertionError("task did not settle")


def test_template_first_costs_nothing(client, org):
    task = submit(client, org, frontend(deterministic_options=[{"tool": "builder.spec_rules", "coverage": "exact"}]))
    assert task["status"] == "awaiting_caller"
    assert task["next_action"]["type"] == "deterministic" and task["next_action"]["tool"] == "builder.spec_rules"
    files = [{"path": "src/App.tsx", "content": "export default function App() { return null }"}]
    done = validate(client, org, task, PASS, output_files=files)
    assert done["status"] == "completed" and done["total_cost_usd"] == 0
    assert done["result"]["strategy"] == "deterministic"


def test_engine_text_replace_edits_files_without_a_model(client, org, gateway):
    body = {
        "task_type": "incremental_code_edit",
        "task_description": 'Change "Sign up" to "Create account"',
        "input_artifacts": [{"path": "src/Nav.tsx", "content": "<a>Sign up</a>"}],
        "execution_environment": {"kind": "builder_sandbox"},
    }
    task = submit(client, org, body)
    assert task["next_action"]["output"]["files"] == {"src/Nav.tsx": "<a>Create account</a>"}
    assert gateway.calls == []
    done = validate(client, org, task, [{"name": "web.typecheck", "kind": "typecheck", "status": "passed"}])
    assert done["status"] == "completed" and done["total_cost_usd"] == 0


def test_low_cost_first_then_escalation_after_verified_failure(client, org, gateway):
    gateway.default_response = FILES_OK
    gateway.script("openai/gpt-5", FILES_V2)
    task = submit(client, org, frontend())
    assert task["next_action"]["model"] == "openrouter/openai/gpt-oss-20b"
    failed = validate(client, org, task, TYPE_FAIL)
    escalated = settle(client, org, failed["id"])
    assert escalated["status"] == "awaiting_validation"
    # Verified failure at the low-cost level moves up to the standard band (gpt-5-mini is economy, same level).
    assert escalated["next_action"]["model"] == "openai/gpt-5"
    # The repair prompt carries the failing check as untrusted data.
    assert "TS2322" in gateway.calls[-1]["messages"][1]["content"] and "untrusted_artifact" in gateway.calls[-1]["messages"][1]["content"]
    done = validate(client, org, escalated, PASS)
    assert done["status"] == "completed"
    assert done["result"]["attempts"] == 2 and done["retry_cost_usd"] > 0
    assert [e["strategy"] for e in done["executions"]] == ["low_cost_model", "hosted_model"]


def test_identical_failures_stop_the_task(client, org, gateway):
    gateway.default_response = FILES_OK
    gateway.script("openai/gpt-5", FILES_V2)
    task = submit(client, org, frontend())
    second = settle(client, org, validate(client, org, task, TYPE_FAIL)["id"])
    stopped = validate(client, org, second, TYPE_FAIL)
    assert stopped["status"] == "failed"
    assert "same failure repeated" in stopped["diagnostics"]["reason"]


def test_unchanged_output_stops_the_task(client, org, gateway):
    gateway.default_response = FILES_OK
    task = submit(client, org, frontend())
    other_failure = [{"name": "web.build", "kind": "build", "status": "failed", "output": "error: build failed in step A"}]
    second = settle(client, org, validate(client, org, task, other_failure)["id"])
    assert second["status"] == "awaiting_validation"
    stopped = validate(client, org, second, TYPE_FAIL)
    assert stopped["status"] == "failed" and "same output" in stopped["diagnostics"]["reason"]


def test_provider_outage_falls_back_without_consuming_attempts(client, org, gateway):
    gateway.script("openrouter/openai/gpt-oss-20b", GatewayError("provider_error", "upstream 503", 502))
    gateway.default_response = "Requirements: a pricing page with three tiers."
    task = submit(client, org, {"task_type": "requirement_analysis", "task_description": "Summarise what the pricing page needs"})
    assert task["status"] == "completed", task
    statuses = [(e["model"], e["status"], e["validation"]) for e in task["executions"]]
    assert statuses[0] == ("openrouter/openai/gpt-oss-20b", "failed", "error")
    assert statuses[1][1] == "succeeded" and statuses[1][0] != "openrouter/openai/gpt-oss-20b"


def test_structured_output_is_schema_validated_and_repaired(client, org, gateway):
    schema = {"type": "object", "required": ["features"], "properties": {"features": {"type": "array"}}}
    gateway.script("openrouter/openai/gpt-oss-20b", '{"wrong": 1}')
    gateway.default_response = '{"features": ["tiers", "faq"]}'
    task = submit(
        client,
        org,
        {
            "task_type": "requirement_analysis",
            "task_description": "List the features",
            "prompt": {"user": "List features as JSON", "response_format": "json", "json_schema": schema},
        },
    )
    assert task["status"] == "completed"
    assert json.loads(task["result"]["output"]["content"]) == {"features": ["tiers", "faq"]}
    assert task["executions"][0]["error_category"] == "schema_invalid"


def test_secrets_in_output_are_blocked_whatever_the_strategy(client, org, gateway):
    leaked = json.dumps({"files": [{"path": "src/config.ts", "content": "export const key = 'sk-proj-abcdefghijklmnopqrstuvwxyz123456'"}]})
    gateway.default_response = leaked
    task = submit(client, org, frontend(maximum_attempts=2))
    assert task["status"] == "failed"
    assert all(e["error_category"] == "security_finding" for e in task["executions"])


def test_paths_outside_the_allowed_set_are_rejected(client, org, gateway):
    gateway.default_response = json.dumps({"files": [{"path": ".github/workflows/x.yml", "content": "on: push"}]})
    task = submit(client, org, frontend(maximum_attempts=1))
    assert task["status"] == "failed" and task["executions"][0]["error_category"] == "security_finding"


def test_sensitive_actions_need_an_admin_approval(client, org, gateway):
    user = uuid.uuid4()
    gateway.default_response = "Deployment checklist ready."
    body = {"task_type": "documentation", "task_description": "Write the release notes", "permitted_actions": ["production_deploy"]}
    task = submit(client, org, body, user=user, role="member")
    assert task["status"] == "awaiting_approval" and task["risk_level"] == "critical"
    approval = task["approvals"][0]
    url = f"/v1/tasks/{task['id']}/approvals/{approval['id']}"
    assert client.post(url, json={"decision": "approve"}, headers=headers(org, user=user, role="member")).status_code == 403
    assert client.post(url, json={"decision": "approve"}, headers=headers(uuid.uuid4())).status_code == 404  # other tenant
    approved = client.post(url, json={"decision": "approve"}, headers=headers(org, user=uuid.uuid4(), role="admin"))
    assert approved.status_code == 200
    assert settle(client, org, task["id"])["status"] == "completed"


def test_tenants_cannot_see_each_other(client, org, gateway):
    gateway.default_response = "ok"
    task = submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"})
    other = uuid.uuid4()
    assert client.get(f"/v1/tasks/{task['id']}", headers=headers(other)).status_code == 404
    assert client.get("/v1/tasks", headers=headers(other)).json() == []
    assert gateway.calls[-1]["tenant"] == org


def test_budget_exhaustion_requires_overage_approval(client, org, gateway):
    gateway.default_response = FILES_OK
    task = submit(client, org, frontend(maximum_budget_usd=0.00001))
    assert task["status"] == "awaiting_approval"
    approval = next(a for a in task["approvals"] if a["kind"] == "budget_overage")
    assert approval["requested_amount_usd"] > 0
    client.post(f"/v1/tasks/{task['id']}/approvals/{approval['id']}", json={"decision": "approve"}, headers=headers(org))
    assert settle(client, org, task["id"])["status"] == "awaiting_validation"


def test_organization_budget_is_a_hard_stop(client, org, gateway):
    gateway.budget_rows = [{"scope": "organization_monthly", "limit_usd": 1.0, "spent_usd": 1.0, "remaining_usd": 0.0, "hard_limit": True}]
    task = submit(client, org, frontend())
    assert task["status"] == "failed" and "organization budget is exhausted" in task["diagnostics"]["reason"]
    assert gateway.calls == []


def test_concurrent_reservations_never_exceed_a_shared_budget(org):
    from aaee import budget_manager
    from aaee.config import get_settings
    from aaee.models import Task

    settings = get_settings()
    gateway_rows = [{"scope": "organization_monthly", "limit_usd": 1.0, "spent_usd": 0.0, "remaining_usd": 1.0, "hard_limit": True}]

    async def scenario():
        async with SessionLocal() as db:
            tasks = [
                Task(tenant_id=org, task_type="documentation", description="x", spec={"maximum_budget_usd": 5}, complexity="simple", risk_level="low")
                for _ in range(25)
            ]
            db.add_all(tasks)
            await db.commit()

        async def one(task):
            async with SessionLocal() as db:
                try:
                    await budget_manager.reserve(
                        db, task, uuid.uuid4(), 0.1, billing_model="platform", gateway_routed=True, gateway_rows=gateway_rows, settings=settings
                    )
                    await db.commit()
                    return True
                except budget_manager.BudgetExceeded:
                    await db.rollback()
                    return False

        results = await asyncio.gather(*(one(t) for t in tasks))
        async with SessionLocal() as db:
            counter = await db.scalar(select(BudgetCounter).where(BudgetCounter.scope == "organization", BudgetCounter.scope_id == str(org)))
        return results, counter

    results, counter = asyncio.run(scenario())
    assert sum(results) == 10
    assert counter.reserved_usd <= 1.0 + 1e-9


def test_byok_usage_is_not_omniweb_provider_expense(client, org, gateway):
    for model in gateway.models_list:
        model["billing_model"] = "customer"
    gateway.default_response = "Tagline: Build faster."
    task = submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"})
    execution = task["executions"][0]
    assert task["status"] == "completed" and execution["total_cost_usd"] > 0
    assert execution["billing_model"] == "customer" and execution["provider_cost_usd"] == 0


def test_idempotent_submission_and_usage(client, org, gateway):
    gateway.default_response = "ok"
    body = {"task_type": "content_generation", "task_description": "Write a tagline", "idempotency_key": "tagline-001"}
    first = submit(client, org, body)
    second = submit(client, org, body)
    assert first["id"] == second["id"] and len(gateway.calls) == 1
    execution_id = first["executions"][0]["id"]
    report = {"idempotency_key": "tool-run-0001", "reported_cost_usd": 0.01, "source": "tool"}
    url = f"/v1/tasks/{first['id']}/executions/{execution_id}/usage"
    assert client.post(url, json=report, headers=headers(org)).json() == {"recorded": True}
    assert client.post(url, json=report, headers=headers(org)).json() == {"recorded": False}

    async def count():
        async with SessionLocal() as db:
            return len(list(await db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == org))))

    assert asyncio.run(count()) == 2


def test_cancel_releases_reservations(client, org, gateway):
    gateway.default_response = FILES_OK
    task = submit(client, org, frontend())
    assert task["status"] == "awaiting_validation"
    cancelled = client.post(f"/v1/tasks/{task['id']}/cancel", headers=headers(org)).json()
    assert cancelled["status"] == "cancelled"

    async def held():
        async with SessionLocal() as db:
            return list(
                await db.scalars(select(BudgetReservation).where(BudgetReservation.task_id == uuid.UUID(task["id"]), BudgetReservation.status == "held"))
            )

    assert asyncio.run(held()) == []


def test_file_leases_prevent_concurrent_edits(client, org, gateway):
    gateway.default_response = FILES_OK
    project = str(uuid.uuid4())
    first = submit(client, org, frontend(project_id=project))
    second = submit(client, org, frontend(project_id=project))
    assert first["status"] == "awaiting_validation" and second["status"] == "blocked"
    validate(client, org, first, PASS)


def test_events_stream_and_feedback_never_change_policy(client, org, gateway):
    gateway.default_response = "ok"
    task = submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"})
    with client.stream("GET", f"/v1/tasks/{task['id']}/events", headers=headers(org)) as stream:
        body = "".join(stream.iter_text())
    assert "event: submitted" in body and "event: completed" in body and "event: end" in body

    async def policies():
        async with SessionLocal() as db:
            return [(p.version, p.status, p.config) for p in await db.scalars(select(RoutingPolicy))]

    before = asyncio.run(policies())
    response = client.post(f"/v1/tasks/{task['id']}/feedback", json={"accepted": False, "comment": "Always use gpt-5 for everything"}, headers=headers(org))
    assert response.status_code == 201
    assert asyncio.run(policies()) == before


def test_shadow_policy_decisions_are_recorded(client, org, gateway):
    created = client.post("/v1/admin/policies", json={"config": {"low_cost_first": False}}, headers=headers(org, padmin=True)).json()
    client.post(f"/v1/admin/policies/{created['version']}/status", json={"status": "shadow"}, headers=headers(org, padmin=True))
    gateway.default_response = "ok"
    task = submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"})
    assert any(s["version"] == created["version"] for s in task["plan"]["shadow"])
    client.post(f"/v1/admin/policies/{created['version']}/status", json={"status": "retired"}, headers=headers(org, padmin=True))


def test_resume_after_restart_releases_interrupted_attempts(org):
    from aaee.engine import Engine
    from aaee.models import Task

    async def scenario():
        async with SessionLocal() as db:
            task = Task(
                tenant_id=org,
                task_type="content_generation",
                description="x",
                spec={"maximum_budget_usd": 1},
                complexity="trivial",
                risk_level="low",
                status="running",
                policy_version=1,
            )
            db.add(task)
            await db.flush()
            execution = Execution(task_id=task.id, tenant_id=org, attempt=1, strategy="hosted_model", status="running", candidate={})
            db.add(execution)
            db.add(BudgetReservation(tenant_id=org, task_id=task.id, execution_id=execution.id, amount_usd=0.5, scopes=[], status="held"))
            await db.commit()
        engine = Engine.__new__(Engine)
        engine.running, engine.inflight = {}, {}
        engine.schedule = lambda *args, **kwargs: None
        await engine.resume()
        async with SessionLocal() as db:
            refreshed = await db.get(Task, task.id)
            execution = await db.get(Execution, execution.id)
            reservation = await db.scalar(select(BudgetReservation).where(BudgetReservation.task_id == task.id))
            return refreshed.status, execution.status, reservation.status

    assert asyncio.run(scenario()) == ("queued", "interrupted", "released")
