"""Analytics, budgets, audit, and benchmarks: scoping and safety rules."""

import json
import time
import uuid

from .conftest import headers
from .test_engine import FILES_OK, PASS, frontend, submit, validate


def test_analytics_report_cost_per_success_by_strategy_and_phase(client, org, gateway):
    gateway.default_response = FILES_OK
    task = submit(client, org, frontend())
    validate(client, org, task, PASS)
    gateway.default_response = "Tagline: Ship it."
    submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"})
    report = client.get("/v1/admin/analytics", headers=headers(org)).json()
    summary = report["summary"]
    assert report["scope"] == "organization" and summary["tasks"] == 2 and summary["completed"] == 2
    assert summary["cost_per_success_usd"] == round(summary["total_cost_usd"] / 2, 6)
    phases = {row["name"]: row for row in report["by_phase"]}
    assert set(phases) == {"implementation", "discovery"}
    assert {row["name"] for row in report["by_strategy"]} <= {"low_cost_model", "hosted_model", "deterministic"}
    assert report["savings"]["baseline_estimated_usd"] >= report["savings"]["actual_usd"]
    assert "not provider-enforced" in report["disclaimer"]


def test_analytics_are_tenant_scoped_and_platform_view_needs_platform_admin(client, org, gateway):
    gateway.default_response = "Tagline: Ship it."
    submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"})
    other = uuid.uuid4()
    assert client.get("/v1/admin/analytics", headers=headers(other)).json()["summary"]["tasks"] == 0
    assert client.get("/v1/admin/analytics", headers=headers(org, role="member")).status_code == 403
    assert client.get("/v1/admin/analytics?scope=platform", headers=headers(org)).status_code == 403
    platform = client.get("/v1/admin/analytics?scope=platform", headers=headers(org, padmin=True)).json()
    assert platform["scope"] == "platform" and platform["summary"]["tasks"] >= 1


def test_user_budgets_are_isolated_per_organization(client, org, gateway):
    user = uuid.uuid4()
    attacker = uuid.uuid4()
    # Another organization's admin sets a zero budget for this user ID; it must not apply here.
    hostile = client.put("/v1/admin/budgets", json={"scope": "user", "scope_id": str(user), "limit_usd": 0}, headers=headers(attacker))
    assert hostile.status_code == 200
    gateway.default_response = "Tagline: Ship it."
    task = submit(client, org, {"task_type": "content_generation", "task_description": "Write a tagline"}, user=user)
    assert task["status"] == "completed"
    assert client.put("/v1/admin/budgets", json={"scope": "platform", "limit_usd": 5}, headers=headers(org)).status_code == 403
    own = client.put("/v1/admin/budgets", json={"scope": "user", "scope_id": str(user), "limit_usd": 0}, headers=headers(org))
    assert own.status_code == 200
    blocked = submit(client, org, {"task_type": "content_generation", "task_description": "Write another tagline"}, user=user)
    assert blocked["status"] in {"blocked", "failed", "awaiting_approval", "needs_human"}
    listed = client.get("/v1/admin/budgets", headers=headers(org)).json()
    assert [b["scope_id"] for b in listed["limits"]] == [str(user)]
    audit = client.get("/v1/admin/audit", headers=headers(org)).json()
    assert audit[0]["action"] == "budget.update"
    assert all(e["target"] != f"user:{user}" or e["actor"].startswith("owner") for e in audit)


def test_benchmarks_need_platform_admin_confirmation_and_respect_the_cap(client, org, gateway):
    body = {"models": ["openrouter/openai/gpt-oss-20b", "mystery/unpriced-model", "openai/gpt-5"], "budget_usd": 0.001}
    assert client.post("/v1/admin/benchmarks", json=body, headers=headers(org)).status_code == 403
    assert client.post("/v1/admin/benchmarks", json=body, headers=headers(org, padmin=True)).status_code == 422
    body["models"][1] = "openrouter/mystery/unpriced-model"
    gateway.default_response = json.dumps({"entities": [{"name": "task", "fields": [{"name": "title"}, {"name": "due_date"}]}]})
    started = client.post("/v1/admin/benchmarks", json={**body, "confirm_billable": True}, headers=headers(org, padmin=True))
    assert started.status_code == 202, started.text
    for _ in range(100):
        runs = client.get("/v1/admin/benchmarks", headers=headers(org, padmin=True)).json()
        if runs[0]["status"] not in {"queued", "running"}:
            break
        time.sleep(0.05)
    run = runs[0]
    assert run["status"] == "completed" and run["spent_usd"] <= 0.001
    results = {r["key"]: r for r in run["results"]}
    assert "unknown" in results["openrouter/mystery/unpriced-model"]["skipped"]
    assert results["openai/gpt-5"]["skipped"] == "The benchmark budget cap was reached"
    assert results["openrouter/openai/gpt-oss-20b"]["cases"][0]["passed"] is True
    # Benchmark results are reported, never folded into routing statistics.
    rows = client.get("/v1/admin/performance?scope=platform", headers=headers(org, padmin=True)).json()["rows"]
    assert not any(r["task_type"] == "architecture_design" for r in rows)


def test_content_only_code_output_still_runs_mandatory_gates(client, org, gateway):
    leaked = json.dumps({"spec": {"name": "x"}, "note": "use sk-proj-abcdefghijklmnopqrstuvwx1234"})
    gateway.default_response = leaked
    task = submit(
        client,
        org,
        {
            "task_type": "incremental_code_edit",
            "task_description": "Rename the app",
            "prompt": {"system": "Return the updated spec as JSON", "user": "Rename the app to Nimbus", "response_format": "json"},
        },
    )
    assert task["status"] in {"failed", "needs_human", "blocked"} or task["next_action"]["type"] != "result"
    gateway.default_response = json.dumps({"spec": {"name": "Nimbus"}, "changes": ["Renamed the app"]})
    clean = submit(
        client,
        org,
        {
            "task_type": "incremental_code_edit",
            "task_description": "Rename the app",
            "prompt": {"system": "Return the updated spec as JSON", "user": "Rename the app to Nimbus", "response_format": "json"},
        },
    )
    assert clean["status"] == "awaiting_validation"
    done = validate(client, org, clean, [{"name": "web.build", "kind": "build", "status": "passed"}])
    assert done["status"] == "completed"
