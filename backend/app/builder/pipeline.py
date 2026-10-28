"""The builder graph: specification → migration plan → code → checks → repair → preview.

Nodes are LangGraph nodes. After every node the run's state is written to `generation_runs`, so a
run interrupted by a restart resumes from the node it was in, and a run waiting for an approval
resumes from the node after the decision. Only one run per project is active at a time.

Agents (all through the model gateway, never with provider keys in this process):
- architect: conversation → AppSpec (heuristic parser when no provider is configured)
- editor: change request → updated AppSpec and optional file patches (heuristic parser fallback)
- repair: failing check output → file patches, escalating from the standard to the advanced tier
Generated code only ever executes inside the sandbox.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from ..config import Settings, get_settings
from ..database import SessionLocal
from ..models import (
    AgentExecution,
    Approval,
    Checkpoint,
    Conversation,
    GenerationRun,
    Message,
    Project,
)
from ..schemas import Principal
from ..services import gateway
from . import edits, migrations, preview, templates, verify
from .sandbox import SandboxUnavailable
from .spec import ARCHITECT_SYSTEM_PROMPT, AppSpec, heuristic_spec, parse_model_spec
from .store import ProjectStore, StoreError, clean_path

logger = logging.getLogger("omniweb.pipeline")
ACTIVE = {"queued", "running"}
AGENT_PATHS = re.compile(r"^(apps/web/src/|apps/mobile/src/|apps/mobile/App\.tsx$|services/api/app/|packages/api-client/src/)")
_tasks: dict[str, asyncio.Task] = {}


class BuildState(TypedDict, total=False):
    run_id: str
    project_id: str
    kind: str
    instruction: str
    spec: dict | None
    changes: list[str]
    files: dict[str, str]
    migration: dict | None
    approved: bool
    approval_id: str | None
    restore_sha: str | None
    undo_of: str | None
    action: str
    applied: dict
    commit_sha: str | None
    verify: dict
    repair_attempts: int
    tier: str
    outcome: str
    message: str
    resume_at: str
    used_model: bool


def now() -> datetime:
    return datetime.now(UTC)


class NoChange(Exception):
    pass


# -- persistence ------------------------------------------------------------------------------


async def _save(run_id: str, state: BuildState, **fields: Any) -> None:
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, uuid.UUID(run_id))
        if not run:
            return
        run.state = json.loads(json.dumps(state, default=str))
        for key, value in fields.items():
            setattr(run, key, value)
        run.updated_at = now()
        await db.commit()


async def _step(run_id: str, name: str, status: str, detail: str = "") -> None:
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, uuid.UUID(run_id))
        if not run:
            return
        steps = [s for s in run.steps if not (s["name"] == name and s["status"] == "running")]
        steps.append({"name": name, "status": status, "detail": detail[:2000], "at": now().isoformat()})
        run.steps = steps[-60:]
        run.stage = name
        await db.commit()


async def _project(db, state: BuildState) -> Project:
    project = await db.get(Project, uuid.UUID(state["project_id"]))
    if not project:
        raise RuntimeError("Project was deleted")
    return project


def node(name: str):
    """Wraps a node so state is saved before and after it runs."""

    def wrap(fn):
        async def run(state: BuildState) -> BuildState:
            state = {**state, "resume_at": name}
            await _save(state["run_id"], state, stage=name, status="running")
            await _step(state["run_id"], name, "running")
            try:
                update = await fn(state)
            except NoChange as exc:
                update = {"outcome": "no_change", "message": str(exc)}
            except Exception as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.exception("node %s failed", name)
                await _step(state["run_id"], name, "failed", str(exc))
                return {**state, "outcome": "error", "message": f"{name} failed: {exc}"}
            merged = {**state, **update}
            await _step(state["run_id"], name, "done", update.get("detail", "") if isinstance(update, dict) else "")
            merged.pop("detail", None)
            await _save(state["run_id"], merged)
            return merged

        run.__name__ = name
        return run

    return wrap


# -- model access -----------------------------------------------------------------------------


async def ask_model(state: BuildState, agent: str, system: str, user: str, tier: str | None = None, max_tokens: int = 6000) -> dict | None:
    """Calls the gateway. Returns None when only the development model is configured or the call fails."""
    settings = get_settings()
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, uuid.UUID(state["run_id"]))
        project = await _project(db, state)
        principal = Principal(user_id=run.requested_by or project.owner_id, organization_id=project.organization_id, email="builder@omniweb.local", role="member")
        execution = AgentExecution(project_id=project.id, organization_id=project.organization_id, agent=agent, stage=state.get("resume_at", agent), status="running", request_id=uuid.uuid4().hex)
        db.add(execution)
        await db.commit()
        payload = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "agent": agent,
            "request_id": execution.request_id,
            "max_output_tokens": max_tokens,
            "complexity": "complex" if agent == "repair" else "normal",
            "response_format": {"type": "json_object"},
        }
        if tier:
            payload["tier"] = tier
        try:
            result = await gateway.call(settings, principal, "POST", "/v1/chat", project_id=project.id, json=payload)
        except HTTPException as exc:
            execution.status = "failed"
            execution.detail = str(exc.detail)[:500]
            execution.finished_at = now()
            await db.commit()
            return None
        execution.status = "succeeded"
        execution.model = f"{result['provider']}/{result['model_id']}"
        execution.cost_usd = result["usage"]["cost_usd"]
        execution.attempts = result.get("attempts", [])
        execution.finished_at = now()
        run.cost_usd = (run.cost_usd or 0) + result["usage"]["cost_usd"]
        await db.commit()
    return None if result.get("development_model") else result


# -- nodes ------------------------------------------------------------------------------------


@node("understand")
async def understand(state: BuildState) -> BuildState:
    async with SessionLocal() as db:
        project = await _project(db, state)
        current = AppSpec.model_validate(project.spec) if project.spec else None
        kind = state["kind"]
        if kind == "verify":
            if not current:
                raise NoChange("Generate the app before running checks.")
            return {"spec": current.model_dump(), "changes": [], "detail": "Checking the current code"}
        if kind == "restore":
            checkpoint = await db.scalar(select(Checkpoint).where(Checkpoint.project_id == project.id, Checkpoint.sha == state["restore_sha"]))
            if not checkpoint or not checkpoint.spec:
                raise NoChange("That checkpoint can't be restored.")
            return {"spec": checkpoint.spec, "changes": [f"Restored {checkpoint.message}"], "detail": f"Restoring {checkpoint.sha[:7]}"}
        conversation = await db.scalar(select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.created_at))
        history = list(await db.scalars(select(Message).where(Message.conversation_id == conversation.id, Message.role == "user").order_by(Message.created_at))) if conversation else []
        template, prompt, name = project.template, project.prompt, project.name
    if kind == "generate" or current is None:
        fallback = heuristic_spec(" ".join([prompt, *(m.content for m in history[-6:])]), template, name)
        request = (
            f"Template: {template} (targets {fallback.targets}). App name: {name}.\n\nOriginal request:\n{prompt}\n\n"
            + ("Follow-up messages:\n" + "\n".join(f"- {m.content}" for m in history[-10:]) if history else "")
            + f"\n\nA draft specification for reference:\n{fallback.model_dump_json()}"
        )
        result = await ask_model(state, "architect", ARCHITECT_SYSTEM_PROMPT, request)
        spec = parse_model_spec(result["content"], fallback) if result else None
        used = spec is not None
        spec = spec or fallback
        return {
            "spec": spec.model_dump(),
            "used_model": used,
            "changes": [f"Planned {len(spec.entities)} data models: {', '.join(e.label for e in spec.entities)}"],
            "detail": ("Specification from the architect agent" if used else "Specification from the built-in parser (no AI provider configured)"),
        }
    instruction = state.get("instruction", "")
    result = await ask_model(
        state, "editor", edits.EDIT_SYSTEM_PROMPT, f"Current specification:\n{current.model_dump_json()}\n\nChange request:\n{instruction}"
    )
    if result:
        parsed = _parse_edit(result["content"], current)
        if parsed:
            spec, changes, files = parsed
            return {"spec": spec.model_dump(), "changes": changes, "files": files, "used_model": True, "detail": "; ".join(changes)[:500]}
    notes: list[str] = []
    edited = edits.apply_instruction(current, instruction, notes)
    if not edited and notes:
        raise NoChange(" ".join(dict.fromkeys(notes)) + " Nothing needed to change.")
    if not edited:
        raise NoChange(
            "I couldn't turn that into a change without an AI provider. Try something like “add a due date field to tasks”, "
            "“remove the notes field from clients”, “add invoices”, “make it green”, or “add sign-in”. "
            "You can also edit any file directly in the Code tab."
        )
    return {"spec": edited.spec.model_dump(), "changes": edited.changes, "files": {}, "used_model": False, "detail": "; ".join(edited.changes)}


def _parse_edit(content: str, current: AppSpec) -> tuple[AppSpec, list[str], dict[str, str]] | None:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        spec = AppSpec.model_validate(data.get("spec") or current.model_dump())
    except (ValueError, TypeError):
        return None
    files = {}
    for path, text in (data.get("files") or {}).items():
        try:
            path = clean_path(path)
        except StoreError:
            continue
        if AGENT_PATHS.match(path) and isinstance(text, str) and len(text) < 200_000:
            files[path] = text
    changes = [str(c)[:200] for c in data.get("changes") or []][:10] or ["Updated the app"]
    return spec, changes, files


@node("plan")
async def plan(state: BuildState) -> BuildState:
    async with SessionLocal() as db:
        project = await _project(db, state)
        previous = AppSpec.model_validate(project.spec) if project.spec else None
        target = AppSpec.model_validate(state["spec"])
        if previous and previous.model_dump() == target.model_dump() and not state.get("files") and state["kind"] == "edit":
            raise NoChange("That's already how the app works, so nothing changed.")
        migration = migrations.plan(previous, target, project.migrations or [])
        if migration and migration["destructive"] and not state.get("approved"):
            approval = Approval(
                project_id=project.id,
                organization_id=project.organization_id,
                kind="destructive_migration",
                summary=f"Delete data: {'; '.join(migration['destructive_summary'])}"[:300],
                details={"migration": migration, "changes": state.get("changes", [])},
                run_id=uuid.UUID(state["run_id"]),
                requested_by="agent:planner",
            )
            db.add(approval)
            await db.commit()
            return {"migration": migration, "approval_id": str(approval.id), "outcome": "awaiting_approval", "detail": approval.summary}
    return {"migration": migration, "detail": migration["message"] if migration else "No database changes"}


@node("apply")
async def apply(state: BuildState) -> BuildState:
    settings = get_settings()
    async with SessionLocal() as db:
        project = await _project(db, state)
        store = ProjectStore(settings, project.id)
        await store.init(project.github_default_branch or "main")
        spec = AppSpec.model_validate(state["spec"])
        history = list(project.migrations or [])
        migration = state.get("migration")
        if migration and all(m["revision"] != migration["revision"] for m in history):
            history.append(migration)
        if state["kind"] == "restore" and state.get("restore_sha"):
            await store.checkout_tree(state["restore_sha"])
        if state["kind"] != "verify":
            result = store.apply(templates.render(spec, history))
            for path, content in (state.get("files") or {}).items():
                store.write(path, content)
                store.adopt(path)
                result.written.append(path)
        else:
            result = None
        project.spec = spec.model_dump()
        project.migrations = history
        project.name = spec.name if state["kind"] != "generate" else project.name
        project.generation_status = "building"
        await db.commit()
    if state["kind"] == "verify":
        sha = await store.head()
        return {"commit_sha": sha, "applied": {"written": [], "deleted": [], "preserved": []}, "detail": "Using the current commit"}
    changes = state.get("changes") or []
    label = {"generate": "Generate", "restore": "Restore", "edit": "Edit"}.get(state["kind"], "Update")
    message = f"{label}: {changes[0] if changes else spec.name}"
    if state.get("action") in {"undo", "redo"}:
        message = f"{state['action'].title()}: {changes[0].removeprefix('Restored ') if changes else ''}"
    sha = await store.commit(message, "agent") or await store.head()
    applied = {"written": result.written, "deleted": result.deleted, "preserved": result.preserved}
    async with SessionLocal() as db:
        project = await _project(db, state)
        parent = project.head_sha
        if sha and sha != parent and not await db.scalar(select(Checkpoint).where(Checkpoint.project_id == project.id, Checkpoint.sha == sha)):
            db.add(
                Checkpoint(
                    project_id=project.id,
                    sha=sha,
                    parent_sha=parent,
                    message=message[:300],
                    author="agent",
                    run_id=uuid.UUID(state["run_id"]),
                    restores_sha=state.get("restore_sha"),
                    action=state.get("action") or ("restore" if state["kind"] == "restore" else "change"),
                    undo_of=state.get("undo_of"),
                    spec=project.spec,
                    migrations=project.migrations,
                )
            )
        project.head_sha = sha
        await db.commit()
    detail = f"{len(result.written)} files written, {len(result.deleted)} removed"
    if result.preserved:
        detail += f", kept your edits to {len(result.preserved)}"
    return {"commit_sha": sha, "applied": applied, "detail": detail}


@node("verify")
async def check(state: BuildState) -> BuildState:
    settings = get_settings()
    store = ProjectStore(settings, state["project_id"])
    spec = AppSpec.model_validate(state["spec"])

    async def progress(step, result):
        if result is None:
            await _step(state["run_id"], f"check:{step.name}", "running", step.label)
        else:
            await _step(state["run_id"], f"check:{step.name}", "done" if result.ok else "failed", f"{step.label} — {'passed' if result.ok else 'failed'} in {result.duration:.1f}s")

    try:
        results, root = await verify.run_checks(settings, store, spec.targets, state["run_id"], progress)
    except SandboxUnavailable as exc:
        return {"verify": {"ok": False, "unavailable": str(exc), "steps": [], "failed": []}, "detail": str(exc)}
    summary = verify.summarize(results)
    summary["build_dir"] = str(root)
    passed = sum(1 for r in results if r.ok)
    return {"verify": summary, "detail": f"{passed}/{len(results)} checks passed"}


@node("repair")
async def repair(state: BuildState) -> BuildState:
    settings = get_settings()
    attempt = state.get("repair_attempts", 0) + 1
    tier = "standard" if attempt == 1 else "advanced"
    store = ProjectStore(settings, state["project_id"])
    failures = [s for s in state["verify"]["steps"] if not s["ok"]]
    mentioned = set()
    for failure in failures:
        mentioned |= set(re.findall(r"((?:apps|services|packages)/[\w./-]+\.(?:tsx?|py))", failure["output"]))
        mentioned |= {f"services/api/{p}" for p in re.findall(r"\b(app/[\w/]+\.py)", failure["output"])}
        mentioned |= {f"apps/web/{p}" for p in re.findall(r"\b(src/[\w/.-]+\.tsx?)", failure["output"])}
    sources = {}
    for path in sorted(mentioned)[:8]:
        try:
            sources[path] = store.read(path)
        except StoreError:
            continue
    request = (
        "These checks failed:\n" + "\n\n".join(f"## {f['label']}\n{f['output'][-4000:]}" for f in failures)
        + "\n\nRelevant files:\n" + "\n\n".join(f"### {p}\n```\n{c[:12000]}\n```" for p, c in sources.items())
        + '\n\nRespond with JSON only: {"files": {"<path>": "<complete corrected file>"}, "explanation": "..."}. '
        "Only change files under apps/web/src, apps/mobile/src, apps/mobile/App.tsx, services/api/app, or packages/api-client/src."
    )
    system = "You are Omniweb's repair agent. Fix the failing checks with the smallest correct change. Never weaken or delete tests."
    result = await ask_model(state, "repair", system, request, tier=tier, max_tokens=8000)
    if not result:
        return {"repair_attempts": attempt, "outcome": "failed", "message": "Checks failed, and automatic repair needs an AI provider (Settings → AI providers).", "detail": "No model available"}
    parsed = _parse_edit(result["content"], AppSpec.model_validate(state["spec"]))
    files = parsed[2] if parsed else {}
    if not files:
        return {"repair_attempts": attempt, "tier": tier, "detail": "The repair agent did not return a usable patch"}
    for path, content in files.items():
        store.write(path, content)
        store.adopt(path)
    sha = await store.commit(f"Repair: fix {', '.join(f['name'] for f in failures)}"[:300], "agent")
    async with SessionLocal() as db:
        project = await _project(db, state)
        if sha:
            db.add(Checkpoint(project_id=project.id, sha=sha, parent_sha=project.head_sha, message=f"Repair attempt {attempt}", author="agent", run_id=uuid.UUID(state["run_id"]), spec=project.spec, migrations=project.migrations))
            project.head_sha = sha
        await db.commit()
    return {"repair_attempts": attempt, "tier": tier, "commit_sha": sha or state.get("commit_sha"), "detail": f"Patched {len(files)} files ({tier} tier)"}


@node("finalize")
async def finalize(state: BuildState) -> BuildState:
    settings = get_settings()
    result = state.get("verify") or {}
    spec = AppSpec.model_validate(state["spec"])
    ok = bool(result.get("ok"))
    published = None
    async with SessionLocal() as db:
        project = await _project(db, state)
        if ok and result.get("build_dir"):
            project.preview_token = project.preview_token or preview.new_token()
            await db.commit()
            from pathlib import Path

            published = await preview.publish(settings, project.preview_token, state["commit_sha"], Path(result["build_dir"]), spec.targets)
            verify.cleanup(Path(result["build_dir"]))
        checkpoint = await db.scalar(select(Checkpoint).where(Checkpoint.project_id == project.id, Checkpoint.sha == state.get("commit_sha")))
        if checkpoint:
            checkpoint.verified = ok
        project.last_build = {
            "ok": ok,
            "sha": state.get("commit_sha"),
            "steps": [{k: v for k, v in s.items() if k != "output"} | {"output": s["output"][-6000:]} for s in result.get("steps", [])],
            "failed": result.get("failed", []),
            "unavailable": result.get("unavailable"),
            "preview": published,
            "finished_at": now().isoformat(),
        }
        project.generation_status = "ready" if ok else "needs_attention"
        project.updated_at = now()
        await db.commit()
    if not ok and result.get("build_dir"):
        from pathlib import Path

        verify.cleanup(Path(result["build_dir"]))
    return {"outcome": "succeeded" if ok else "failed", "detail": "Preview published" if published else "Checks did not pass"}


def route_after_plan(state: BuildState) -> str:
    return END if state.get("outcome") in {"awaiting_approval", "no_change", "error"} else "apply"


def route_after_verify(state: BuildState) -> str:
    if state.get("outcome") == "error":
        return END
    result = state.get("verify") or {}
    if result.get("ok") or result.get("unavailable"):
        return "finalize"
    if state.get("repair_attempts", 0) < get_settings().max_repair_attempts:
        return "repair"
    return "finalize"


def route_after_repair(state: BuildState) -> str:
    if state.get("outcome") in {"failed", "error"}:
        return "finalize"
    return "verify"


def build_graph():
    graph = StateGraph(BuildState)
    graph.add_node("understand", understand)
    graph.add_node("plan", plan)
    graph.add_node("apply", apply)
    graph.add_node("verify", check)
    graph.add_node("repair", repair)
    graph.add_node("finalize", finalize)
    graph.add_conditional_edges(START, lambda s: s.get("resume_at") or "understand", ["understand", "plan", "apply", "verify", "repair", "finalize"])
    graph.add_conditional_edges("understand", lambda s: END if s.get("outcome") in {"no_change", "error"} else "plan", ["plan", END])
    graph.add_conditional_edges("plan", route_after_plan, ["apply", END])
    graph.add_conditional_edges("apply", lambda s: END if s.get("outcome") == "error" else "verify", ["verify", END])
    graph.add_conditional_edges("verify", route_after_verify, ["repair", "finalize", END])
    graph.add_conditional_edges("repair", route_after_repair, ["verify", "finalize"])
    graph.add_edge("finalize", END)
    return graph.compile()


GRAPH = build_graph()


# -- run lifecycle ----------------------------------------------------------------------------


def summary_message(state: BuildState) -> str:
    outcome = state.get("outcome")
    spec = AppSpec.model_validate(state["spec"]) if state.get("spec") else None
    changes = state.get("changes") or []
    if outcome == "no_change":
        return state.get("message", "Nothing changed.")
    if outcome == "awaiting_approval":
        return "This change deletes data, so it needs your approval before I continue: " + "; ".join((state.get("migration") or {}).get("destructive_summary", [])) + ". Review it in the banner above the preview."
    if outcome == "error":
        return f"The build stopped: {state.get('message', 'unknown error')}"
    result = state.get("verify") or {}
    steps = result.get("steps", [])
    passed = sum(1 for s in steps if s["ok"])
    lines = []
    if state["kind"] == "generate" and spec:
        targets = {"web": "a React web app", "api": "a FastAPI backend with migrations", "mobile": "an Expo mobile app"}
        lines.append(f"I built **{spec.name}** — {', '.join(targets[t] for t in spec.targets)}" + (", with email sign-in" if spec.auth else "") + ".")
        lines.append("Data models: " + ", ".join(f"{e.label} ({len(e.fields)} fields)" for e in spec.entities) + ".")
    else:
        lines += [f"- {c}" for c in changes]
    preserved = (state.get("applied") or {}).get("preserved") or []
    if preserved:
        lines.append(f"I kept your manual edits to {', '.join(preserved[:5])}{' and others' if len(preserved) > 5 else ''}; those files were not regenerated.")
    if result.get("unavailable"):
        lines.append(f"The code is committed, but nothing was run: {result['unavailable']}")
    elif result.get("ok"):
        lines.append(f"All {passed} checks passed ({', '.join(s['label'].lower() for s in steps)}). The preview is updated.")
    else:
        failed = [s["label"] for s in steps if not s["ok"]]
        lines.append(f"{passed} of {len(steps)} checks passed. Failing: {', '.join(failed)}. The preview still shows the last working version — see the Logs tab.")
        if state.get("message"):
            lines.append(state["message"])
    if not state.get("used_model") and state["kind"] in {"generate", "edit"}:
        lines.append("_No AI provider is configured, so I used Omniweb's built-in planner. Connect one in Settings for open-ended changes._")
    return "\n\n".join(lines)


async def _finish(run_id: str, state: BuildState) -> None:
    outcome = state.get("outcome") or "failed"
    status = {"succeeded": "succeeded", "awaiting_approval": "awaiting_approval", "no_change": "no_change"}.get(outcome, "failed")
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, uuid.UUID(run_id))
        project = await db.get(Project, run.project_id) if run else None
        if not run or not project:
            return
        run.status = status
        run.stage = "done" if status != "awaiting_approval" else "awaiting_approval"
        run.state = json.loads(json.dumps(state, default=str))
        run.checkpoint_sha = state.get("commit_sha")
        run.error = state.get("message") if status == "failed" else None
        if status != "awaiting_approval":
            run.finished_at = now()
        if status in {"no_change", "awaiting_approval"} and project.generation_status in {"building", "planning"}:
            project.generation_status = "ready" if project.head_sha else "draft"
        if outcome == "error":
            project.generation_status = "needs_attention" if project.head_sha else "draft"
        if state["kind"] != "verify" or status == "failed":
            conversation = await db.scalar(select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.created_at))
            if conversation:
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        project_id=project.id,
                        organization_id=project.organization_id,
                        role="assistant",
                        agent="builder",
                        content=summary_message(state),
                        cost_usd=run.cost_usd or 0,
                        development_model=not state.get("used_model", False),
                    )
                )
        await db.commit()


async def execute(run_id: str) -> None:
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, uuid.UUID(run_id))
        if not run or run.status not in ACTIVE:
            return
        state: BuildState = {**(run.state or {}), "run_id": run_id, "project_id": str(run.project_id), "kind": run.kind, "instruction": run.instruction}
        state.pop("outcome", None)
        run.status = "running"
        await db.commit()
    try:
        final = await GRAPH.ainvoke(state, {"recursion_limit": 40})
        await _finish(run_id, final)
    except asyncio.CancelledError:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, uuid.UUID(run_id))
            if run and run.status in ACTIVE:
                run.status = "cancelled"
                run.finished_at = now()
                project = await db.get(Project, run.project_id)
                if project and project.generation_status == "building":
                    project.generation_status = "ready" if project.head_sha else "draft"
                await db.commit()
        raise
    except Exception as exc:
        logger.exception("run %s crashed", run_id)
        await _finish(run_id, {**state, "outcome": "error", "message": str(exc)[:500]})
    finally:
        _tasks.pop(run_id, None)


def launch(run_id: uuid.UUID | str) -> None:
    key = str(run_id)
    if key not in _tasks:
        _tasks[key] = asyncio.create_task(execute(key))


async def cancel(run_id: uuid.UUID | str) -> bool:
    task = _tasks.get(str(run_id))
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: S110
            pass
        return True
    return False


async def create_run(db, project: Project, principal: Principal, kind: str, instruction: str = "", **state: Any) -> GenerationRun:
    active = await db.scalar(select(GenerationRun).where(GenerationRun.project_id == project.id, GenerationRun.status.in_(ACTIVE | {"awaiting_approval"})))
    if active:
        raise HTTPException(status_code=409, detail="Another build is in progress or waiting for approval. Wait for it, or cancel it first.")
    run = GenerationRun(
        project_id=project.id,
        organization_id=project.organization_id,
        requested_by=principal.user_id,
        kind=kind,
        instruction=instruction[:8000],
        status="queued",
        state={k: v for k, v in state.items() if v is not None},
    )
    db.add(run)
    project.generation_status = "building"
    await db.flush()
    return run


async def resume_all(settings: Settings) -> None:
    """Restarts runs interrupted by a restart, and the preview APIs of published projects."""
    async with SessionLocal() as db:
        runs = list(await db.scalars(select(GenerationRun).where(GenerationRun.status.in_(ACTIVE))))
        tokens = [p for p in await db.scalars(select(Project.preview_token).where(Project.preview_token.is_not(None)))]
    for run in runs:
        logger.info("resuming run %s at %s", run.id, (run.state or {}).get("resume_at", "start"))
        launch(run.id)
    for token in tokens:
        try:
            await preview.restore(settings, token)
        except Exception:
            logger.exception("could not restore preview %s", token)
