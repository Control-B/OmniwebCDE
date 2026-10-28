import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

from app.builder import migrations, sandbox, toolchain
from app.builder.edits import apply_instruction
from app.builder.spec import heuristic_spec
from app.builder.store import ProjectStore, StoreError
from app.config import get_settings
from app.main import app
from app.schemas import Principal
from app.security import DEV_ORG_ID, get_principal

PROMPT = 'A tool library called "Toolshed" where neighbours lend tools, with a login'


def toolshed():
    return heuristic_spec(PROMPT, "full-stack", "Toolshed")


def test_heuristic_spec_and_edits():
    spec = toolshed()
    assert spec.targets == ["web", "api"] and spec.auth
    assert [e.name for e in spec.entities] == ["Tool", "Loan"]
    edited = apply_instruction(spec, "Add a phone number and email to loans")
    loan = next(e for e in edited.spec.entities if e.name == "Loan")
    assert {f.name: f.type for f in loan.fields}["email"] == "email"
    assert apply_instruction(spec, "remove the notes field from tools") is None
    assert apply_instruction(spec, "make it green").spec.accent == "#16a34a"
    assert "mobile" in apply_instruction(spec, "add a mobile app").spec.targets
    assert apply_instruction(spec, "do something magical") is None
    notes: list[str] = []
    assert apply_instruction(spec, "tools should have a condition", notes) is None
    assert notes == ["Tools already have a Condition field."]


def test_migrations_are_append_only_and_flag_destructive_changes():
    spec = toolshed()
    first = migrations.plan(None, spec, [])
    assert first["revision"] == "0001" and not first["destructive"]
    added = apply_instruction(spec, "add a deposit amount to loans").spec
    second = migrations.plan(spec, added, [first])
    assert second["down_revision"] == "0001" and second["ops"] == [
        {
            "op": "add_column",
            "table": "loans",
            "field": {"name": "deposit_amount", "type": "number"},
        }
    ]
    removed = apply_instruction(added, "remove tools").spec
    third = migrations.plan(added, removed, [first, second])
    assert third["destructive"] and third["destructive_summary"] == [
        "Drop table tools and all its data"
    ]


def test_store_keeps_user_edits_and_rejects_unsafe_paths(tmp_path):
    settings = get_settings().model_copy(update={"builder_data_dir": str(tmp_path)})
    store = ProjectStore(settings, uuid.uuid4())

    async def scenario():
        await store.init()
        store.apply({"a.txt": "one\n", "b.txt": "two\n"})
        await store.commit("first")
        store.write("a.txt", "mine\n")
        result = store.apply({"a.txt": "one v2\n", "b.txt": "two v2\n", "c.txt": "new\n"})
        assert result.preserved == ["a.txt"] and sorted(result.written) == ["b.txt", "c.txt"]
        assert store.read("a.txt") == "mine\n" and store.user_modified() == ["a.txt"]
        result = store.apply({"a.txt": "one v3\n"})
        assert "b.txt" in result.deleted
        for bad in [
            "../x",
            "/etc/passwd",
            ".git/config",
            ".omniweb/manifest.json",
            "apps/node_modules/x.js",
        ]:
            with pytest.raises(StoreError):
                store.write(bad, "x")
        sha = await store.commit("second", "user")
        assert (await store.log())[0]["author"] == "Omniweb user"
        diff = await store.diff(sha)
        assert {f["path"] for f in diff["files"]} == {"a.txt", "b.txt"}
        assert ".omniweb" not in diff["patch"]

    asyncio.run(scenario())


@pytest.mark.skipif(not shutil.which("unshare"), reason="needs util-linux unshare")
def test_sandbox_hides_host_files_network_and_environment(tmp_path, monkeypatch):
    settings = get_settings()
    if not toolchain.is_ready(settings):
        pytest.skip("toolchain not installed")
    monkeypatch.setenv("OMNIWEB_FAKE_SECRET", "sk-live-should-never-be-visible-123456")
    probe = (
        "ls /workspace | wc -l; ls /home | wc -l; env | sort; echo pid=$$; "
        "python3 -c \"import socket\ntry:\n socket.create_connection(('1.1.1.1', 53), 2); print('net=open')\nexcept OSError: print('net=blocked')\"; "
        "echo sk-abcdefghijklmnopqrstuvwxyz"
    )
    result = asyncio.run(
        sandbox.run(
            settings,
            sandbox.Job(command=["sh", "-c", probe], app_dir=tmp_path),
            toolchain.toolchain_dir(settings),
        )
    )
    if result.exit_code != 0 and "unshare" in result.output:
        pytest.skip("user namespaces are not permitted here")
    lines = result.output.splitlines()
    assert lines[0] == "0" and lines[1] == "0"
    assert "OMNIWEB_FAKE_SECRET" not in result.output and "HOME=/tmp" in result.output
    assert "net=blocked" in result.output
    assert "pid=1" in result.output or any(
        line.startswith("pid=") and int(line[4:]) < 10 for line in lines
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in result.output and "[redacted]" in result.output


def wait(client, project_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/v1/projects/{project_id}/builder").json()
        if state["run"] and state["run"]["status"] not in {"queued", "running"}:
            return state
        time.sleep(0.5)
    raise AssertionError("run did not finish")


@pytest.mark.skipif(not shutil.which("unshare"), reason="needs util-linux unshare")
def test_generate_edit_approve_undo_sync_and_deploy(client, live_gateway):
    if not toolchain.is_ready(get_settings()):
        pytest.skip("toolchain not installed")
    project = client.post("/api/v1/projects", json={"prompt": PROMPT}).json()
    base = f"/api/v1/projects/{project['id']}"
    assert client.post(f"{base}/generate").status_code == 202
    assert client.post(f"{base}/generate").status_code == 409

    state = wait(client, project["id"])
    assert state["run"]["status"] == "succeeded", state["run"]
    assert state["last_build"]["ok"] and [s["name"] for s in state["last_build"]["steps"]] == [
        "web.typecheck",
        "web.test",
        "web.build",
        "api.test",
        "api.migrate",
    ]
    assert state["preview"]["web"] and state["preview"]["api"]["running"]
    messages = client.get(f"{base}/messages").json()
    assert messages[-1]["agent"] == "builder" and "All 5 checks passed" in messages[-1]["content"]

    token = state["preview"]["url"].split("//")[1].split(".")[0]
    socket = Path(get_settings().builder_data_dir).resolve() / "run" / token / "api.sock"

    async def call_preview_api():
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket)), base_url="http://preview"
        ) as api:
            registered = await api.post(
                "/api/auth/register",
                json={"email": "sam@example.com", "password": "correct-horse-9"},
            )
            headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
            created = await api.post("/api/tools", json={"name": "Ladder"}, headers=headers)
            return created.status_code, (await api.get("/api/tools")).status_code

    assert asyncio.run(call_preview_api()) == (201, 401)

    from app import preview_server

    async def browse_preview():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=preview_server.app),
            base_url=f"http://{token}.preview.localhost",
        ) as browser:
            page = await browser.get("/")
            assert page.status_code == 200 and "__omniweb/bridge.js" in page.text
            assert "frame-ancestors" in page.headers["content-security-policy"]
            assert (await browser.get("/api/health")).json() == {"status": "ok"}
            assert (
                "root:" not in (await browser.get("/assets/..%2F..%2F..%2F..%2Fetc%2Fpasswd")).text
            )
            other = await browser.get("/", headers={"host": "ffffffffffffffff.preview.localhost"})
            assert other.status_code == 404

    asyncio.run(browse_preview())

    edit = client.post(f"{base}/edits", json={"instruction": "Add a deposit amount to loans"})
    assert edit.status_code == 202
    state = wait(client, project["id"])
    assert state["run"]["status"] == "succeeded" and state["run"]["changes"] == [
        "Added Deposit amount to Loans"
    ]

    client.post(f"{base}/edits", json={"instruction": "remove the condition field from tools"})
    state = wait(client, project["id"])
    assert (
        state["run"]["status"] == "awaiting_approval"
        and state["approvals"][0]["kind"] == "destructive_migration"
    )
    assert client.post(f"{base}/edits", json={"instruction": "make it green"}).status_code == 409
    decision = client.post(
        f"{base}/approvals/{state['approvals'][0]['id']}/decision", json={"decision": "reject"}
    )
    assert decision.json()["approval"]["status"] == "rejected"
    schema = client.get(f"{base}/schema").json()
    assert (
        "condition" in [f["name"] for f in schema["entities"][0]["fields"]]
        and len(schema["migrations"]) == 2
    )

    dashboard = client.get(
        f"{base}/files/content", params={"path": "apps/web/src/pages/Dashboard.tsx"}
    ).json()["content"]
    saved = client.put(
        f"{base}/files",
        json={
            "path": "apps/web/src/pages/Dashboard.tsx",
            "content": dashboard + "\n// kept by hand\n",
        },
    )
    assert saved.status_code == 200 and saved.json()["run"]["kind"] == "verify"
    assert wait(client, project["id"])["run"]["status"] == "succeeded"
    client.post(f"{base}/edits", json={"instruction": "make it green"})
    state = wait(client, project["id"])
    assert state["run"]["preserved"] == ["apps/web/src/pages/Dashboard.tsx"]

    history = client.get(f"{base}/checkpoints").json()
    assert history["can_undo"] and not history["can_redo"]
    assert client.post(f"{base}/undo").status_code == 202
    assert wait(client, project["id"])["run"]["status"] == "succeeded"
    assert client.get(f"{base}/checkpoints").json()["can_redo"]

    connection = client.post(
        "/api/v1/cloud-connections", json={"label": "Toolshed DO", "token": "dop_v1_mock_token"}
    ).json()
    blocked = client.post(f"{base}/deployments", json={"environment": "development"})
    assert blocked.status_code == 409 and "Push" in blocked.json()["detail"]
    assert (
        client.post(
            f"{base}/github/connect", json={"repo": f"neighbours/toolshed-{uuid.uuid4().hex[:6]}"}
        ).status_code
        == 200
    )
    pushed = client.post(f"{base}/github/push").json()
    clone = Path(client.get(f"{base}/github").json()["clone_url"])
    log = subprocess.run(
        ["git", "--git-dir", str(clone), "log", "--format=%H", "-1", "main"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.strip() == pushed["pushed"]
    assert "token" not in (clone / "config").read_text().lower()

    estimate = client.post(
        f"{base}/deployments/estimate", json={"environment": "production"}
    ).json()
    assert estimate["monthly_usd"] == 30.0
    requested = client.post(
        f"{base}/deployments",
        json={"environment": "production", "cloud_connection_id": connection["id"]},
    )
    assert requested.status_code == 201, requested.text
    approval = requested.json()["approval"]
    assert approval["requires_confirmation"]
    path = f"{base}/approvals/{approval['id']}/decision"
    assert client.post(path, json={"decision": "approve"}).status_code == 422
    approved = client.post(path, json={"decision": "approve", "confirm": project["name"]}).json()
    deployment = approved["deployment"]
    assert deployment["status"] == "live" and deployment["url"].endswith(".mock.ondigitalocean.app")
    assert "dop_v1" not in str(approved)
    rollback = client.post(f"{base}/deployments/{deployment['id']}/rollback").json()
    rolled = client.post(
        f"{base}/approvals/{rollback['approval']['id']}/decision",
        json={"decision": "approve", "confirm": project["name"]},
    ).json()
    assert (
        rolled["deployment"]["status"] == "live"
        and rolled["deployment"]["rollback_of"] == deployment["id"]
    )

    outsider = Principal(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), email="x@example.com", role="owner"
    )
    app.dependency_overrides[get_principal] = lambda: outsider
    assert client.get(f"{base}/builder").status_code == 404
    viewer = Principal(
        user_id=uuid.uuid4(), organization_id=DEV_ORG_ID, email="v@example.com", role="viewer"
    )
    app.dependency_overrides[get_principal] = lambda: viewer
    assert client.post(f"{base}/edits", json={"instruction": "make it blue"}).status_code == 404
    app.dependency_overrides.clear()
