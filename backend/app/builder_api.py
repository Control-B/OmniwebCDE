"""HTTP API for the application builder: builds, code, history, preview, approvals, GitHub, deploys."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .builder import deploy, github, pipeline, preview, toolchain
from .builder.spec import AppSpec
from .builder.store import ProjectStore, StoreError
from .config import Settings, get_settings
from .database import get_db
from .models import (
    Approval,
    Checkpoint,
    CloudConnection,
    Conversation,
    Deployment,
    GenerationRun,
    Message,
    Project,
)
from .projects_api import audit, message_view, project_access
from .providers.digitalocean import DigitalOceanError
from .schemas import Principal
from .security import decrypt_secret, get_principal

router = APIRouter(prefix="/api/v1/projects/{project_id}")


class EditInput(BaseModel):
    instruction: str = Field(min_length=2, max_length=8000)


class FileInput(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=500_000)
    message: str | None = Field(default=None, max_length=200)


class VisualEditInput(BaseModel):
    loc: str = Field(pattern=r"^[A-Za-z0-9_./@-]+:\d+:\d+$", max_length=320)
    text: str | None = Field(default=None, max_length=2000)
    class_name: str | None = Field(default=None, max_length=2000, alias="className")
    model_config = {"populate_by_name": True}


class DecisionInput(BaseModel):
    decision: Literal["approve", "reject"]
    confirm: str | None = Field(default=None, max_length=80)


class GitHubConnectInput(BaseModel):
    repo: str = Field(min_length=3, max_length=140)
    branch: str = Field(default="main", min_length=1, max_length=100)
    installation_id: str | None = Field(default=None, pattern=r"^\d{1,20}$")


class DeployInput(BaseModel):
    environment: Literal["development", "production"] = "development"
    region: str = Field(default="nyc", pattern=r"^[a-z]{3}$")
    cloud_connection_id: uuid.UUID | None = None


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def run_view(run: GenerationRun) -> dict:
    state = run.state or {}
    return {
        "id": str(run.id),
        "kind": run.kind,
        "instruction": run.instruction,
        "status": run.status,
        "stage": run.stage,
        "steps": run.steps,
        "changes": state.get("changes", []),
        "preserved": (state.get("applied") or {}).get("preserved", []),
        "repair_attempts": state.get("repair_attempts", 0),
        "cost_usd": round(run.cost_usd or 0, 6),
        "error": run.error,
        "checkpoint_sha": run.checkpoint_sha,
        "created_at": iso(run.created_at),
        "finished_at": iso(run.finished_at),
    }


def approval_view(a: Approval) -> dict:
    return {
        "id": str(a.id),
        "kind": a.kind,
        "status": a.status,
        "summary": a.summary,
        "details": a.details,
        "estimated_monthly_usd": a.estimated_monthly_usd,
        "requested_by": a.requested_by,
        "requires_confirmation": a.kind in {"production_deployment", "production_rollback"},
        "created_at": iso(a.created_at),
        "decided_at": iso(a.decided_at),
    }


def deployment_view(d: Deployment) -> dict:
    return {
        "id": str(d.id),
        "environment": d.environment,
        "commit_sha": d.commit_sha,
        "region": d.region,
        "status": d.status,
        "url": d.url,
        "estimated_monthly_usd": d.estimated_monthly_usd,
        "rollback_of": str(d.rollback_of) if d.rollback_of else None,
        "approval_id": str(d.approval_id) if d.approval_id else None,
        "log": d.log,
        "created_at": iso(d.created_at),
        "finished_at": iso(d.finished_at),
    }


def checkpoint_view(c: Checkpoint) -> dict:
    return {
        "sha": c.sha,
        "parent_sha": c.parent_sha,
        "message": c.message,
        "author": c.author,
        "action": c.action,
        "verified": c.verified,
        "restores_sha": c.restores_sha,
        "created_at": iso(c.created_at),
    }


def store_for(settings: Settings, project: Project) -> ProjectStore:
    return ProjectStore(settings, project.id)


async def active_run(db: AsyncSession, project: Project) -> GenerationRun | None:
    return await db.scalar(
        select(GenerationRun)
        .where(GenerationRun.project_id == project.id, GenerationRun.status.in_(pipeline.ACTIVE | {"awaiting_approval"}))
        .order_by(GenerationRun.created_at.desc())
    )


async def start(db: AsyncSession, project: Project, principal: Principal, kind: str, instruction: str = "", **state) -> GenerationRun:
    run = await pipeline.create_run(db, project, principal, kind, instruction, **state)
    audit(db, principal, f"builder.run.{kind}", "project", str(project.id))
    await db.commit()
    pipeline.launch(run.id)
    return run


async def add_message(db: AsyncSession, project: Project, principal: Principal, content: str) -> Message:
    conversation = await db.scalar(select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.created_at))
    if not conversation:
        conversation = Conversation(project_id=project.id, organization_id=project.organization_id)
        db.add(conversation)
        await db.flush()
    message = Message(conversation_id=conversation.id, project_id=project.id, organization_id=project.organization_id, author_id=principal.user_id, role="user", content=content)
    db.add(message)
    return message


# -- overview ---------------------------------------------------------------------------------


@router.get("/builder")
async def builder_state(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, role = await project_access(db, project_id, principal)
    run = await active_run(db, project)
    latest = run or await db.scalar(select(GenerationRun).where(GenerationRun.project_id == project.id).order_by(GenerationRun.created_at.desc()))
    approvals = list(await db.scalars(select(Approval).where(Approval.project_id == project.id, Approval.status == "pending").order_by(Approval.created_at)))
    published = preview.current(settings, project.preview_token) if project.preview_token else None
    spec = AppSpec.model_validate(project.spec) if project.spec else None
    return {
        "spec": project.spec,
        "head_sha": project.head_sha,
        "generation_status": project.generation_status,
        "your_role": role,
        "run": run_view(latest) if latest else None,
        "active": bool(run and run.status in pipeline.ACTIVE),
        "approvals": [approval_view(a) for a in approvals],
        "last_build": project.last_build,
        "preview": {
            "url": preview.url_for(settings, project.preview_token) if published else None,
            "sha": published.name if published else None,
            "web": bool(published and (published / "web").is_dir()),
            "mobile": bool(published and (published / "mobile").is_dir()),
            "api": preview.api_status(settings, project.preview_token) if published and spec and "api" in spec.targets else None,
        },
        "toolchain_ready": toolchain.is_ready(settings),
        "sandbox": settings.sandbox_mode,
        "github": {"repo": project.github_repo, "branch": project.github_default_branch, "mode": github.mode(settings), "last_pushed_sha": project.last_pushed_sha},
    }


# -- runs -------------------------------------------------------------------------------------


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    run = await start(db, project, principal, "generate" if not project.spec else "edit", "Regenerate from the requirements" if project.spec else "")
    return run_view(run)


@router.post("/edits", status_code=status.HTTP_202_ACCEPTED)
async def edit(project_id: uuid.UUID, data: EditInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if await active_run(db, project):
        raise HTTPException(status_code=409, detail="Another build is in progress or waiting for approval. Wait for it, or cancel it first.")
    message = await add_message(db, project, principal, data.instruction)
    run = await start(db, project, principal, "edit" if project.spec else "generate", data.instruction)
    return {"run": run_view(run), "user_message": message_view(message)}


@router.get("/runs")
async def list_runs(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    rows = await db.scalars(select(GenerationRun).where(GenerationRun.project_id == project.id).order_by(GenerationRun.created_at.desc()).limit(30))
    return [run_view(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(project_id: uuid.UUID, run_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    run = await db.scalar(select(GenerationRun).where(GenerationRun.id == run_id, GenerationRun.project_id == project.id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    view = run_view(run)
    view["verify"] = [{k: s.get(k) for k in ("name", "label", "ok", "duration", "output")} for s in ((run.state or {}).get("verify") or {}).get("steps", [])]
    return view


@router.post("/runs/{run_id}/cancel")
async def cancel_run(project_id: uuid.UUID, run_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    run = await db.scalar(select(GenerationRun).where(GenerationRun.id == run_id, GenerationRun.project_id == project.id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in pipeline.ACTIVE | {"awaiting_approval"}:
        raise HTTPException(status_code=409, detail="This run has already finished")
    await pipeline.cancel(run.id)
    await db.refresh(run)
    if run.status in pipeline.ACTIVE | {"awaiting_approval"}:
        run.status = "cancelled"
        run.finished_at = now()
    for approval in await db.scalars(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")):
        approval.status = "cancelled"
    await db.refresh(project)
    if project.generation_status == "building":
        project.generation_status = "ready" if project.head_sha else "draft"
    audit(db, principal, "builder.run.cancel", "project", str(project.id))
    await db.commit()
    return run_view(run)


# -- files ------------------------------------------------------------------------------------


@router.get("/files")
async def list_files(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    store = store_for(settings, project)
    if not store.exists:
        return {"files": [], "head": None}
    return {"files": await store.tree(), "head": await store.head()}


@router.get("/files/content")
async def read_file(project_id: uuid.UUID, path: str, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    try:
        content = store_for(settings, project).read(path)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"path": path, "content": content}


async def commit_user_change(db: AsyncSession, project: Project, principal: Principal, store: ProjectStore, message: str) -> dict:
    sha = await store.commit(message, "user")
    if not sha:
        return {"sha": project.head_sha, "changed": False, "run": None}
    db.add(Checkpoint(project_id=project.id, sha=sha, parent_sha=project.head_sha, message=message[:300], author="user", spec=project.spec, migrations=project.migrations))
    project.head_sha = sha
    project.updated_at = now()
    await db.commit()
    run = None
    if not await active_run(db, project) and project.spec:
        run = run_view(await start(db, project, principal, "verify", message))
    return {"sha": sha, "changed": True, "run": run}


@router.put("/files")
async def write_file(project_id: uuid.UUID, data: FileInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    store = store_for(settings, project)
    if not store.exists:
        raise HTTPException(status_code=409, detail="Generate the app before editing files")
    if await active_run(db, project):
        raise HTTPException(status_code=409, detail="Wait for the current build to finish before saving")
    try:
        path = store.write(data.path, data.content)
    except StoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(db, principal, "builder.file.write", "project", str(project.id))
    return await commit_user_change(db, project, principal, store, data.message or f"Edit {path}")


@router.delete("/files")
async def delete_file(project_id: uuid.UUID, path: str, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    store = store_for(settings, project)
    if await active_run(db, project):
        raise HTTPException(status_code=409, detail="Wait for the current build to finish")
    try:
        store.delete(path)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit(db, principal, "builder.file.delete", "project", str(project.id))
    return await commit_user_change(db, project, principal, store, f"Delete {path}")


@router.post("/visual-edit")
async def visual_edit(project_id: uuid.UUID, data: VisualEditInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if data.text is None and data.class_name is None:
        raise HTTPException(status_code=422, detail="Change the text or the classes")
    if await active_run(db, project):
        raise HTTPException(status_code=409, detail="Wait for the current build to finish")
    path, line, column = data.loc.rsplit(":", 2)
    store = store_for(settings, project)
    try:
        source = store.read(path)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail="The selected element's file no longer exists") from exc
    if not path.endswith((".tsx", ".jsx")):
        raise HTTPException(status_code=422, detail="Only JSX elements can be edited visually")
    tc = await toolchain.ensure(settings)
    payload = {"source": source, "line": int(line), "column": int(column)}
    if data.text is not None:
        payload["text"] = data.text
    if data.class_name is not None:
        payload["className"] = data.class_name
    process = await asyncio.create_subprocess_exec(
        str(tc / "bin" / "node"), str(tc / "scripts" / "ast-edit.mjs"), cwd=tc, env={"PATH": "/usr/bin:/bin"},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), 30)
    result = json.loads(out or b'{"error": "The editor did not respond"}')
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    if result["source"] == source:
        return {"sha": project.head_sha, "changed": False, "run": None}
    store.write(path, result["source"])
    audit(db, principal, "builder.visual_edit", "project", str(project.id))
    what = "text" if data.text is not None else "styles"
    return await commit_user_change(db, project, principal, store, f"Visual edit: {what} in {path.rsplit('/', 1)[-1]}")


# -- history ----------------------------------------------------------------------------------


async def _history(db: AsyncSession, project: Project) -> list[Checkpoint]:
    return list(await db.scalars(select(Checkpoint).where(Checkpoint.project_id == project.id).order_by(Checkpoint.created_at.desc())))


def _effective(checkpoint: Checkpoint) -> str:
    return checkpoint.restores_sha or checkpoint.sha


def _undo_target(history: list[Checkpoint]) -> tuple[str, str] | None:
    """(sha to restore, sha being undone) for the newest checkpoint."""
    if not history:
        return None
    by_sha = {c.sha: c for c in history}
    current = _effective(history[0])
    original = by_sha.get(current)
    if not original or not original.parent_sha or original.parent_sha not in by_sha:
        return None
    return _effective(by_sha[original.parent_sha]), current


def _redo_target(history: list[Checkpoint]) -> str | None:
    if not history:
        return None
    head = history[0]
    if head.action == "undo":
        return head.undo_of
    if head.action == "redo":
        for c in history[1:]:
            if c.action == "undo" and c.restores_sha == head.restores_sha:
                return c.undo_of
            if c.action not in {"undo", "redo"}:
                return None
    return None


@router.get("/checkpoints")
async def checkpoints(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    history = await _history(db, project)
    return {"checkpoints": [checkpoint_view(c) for c in history[:100]], "can_undo": _undo_target(history) is not None, "can_redo": _redo_target(history) is not None, "head": project.head_sha}


@router.get("/checkpoints/{sha}/diff")
async def checkpoint_diff(project_id: uuid.UUID, sha: str, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    if not await db.scalar(select(Checkpoint.id).where(Checkpoint.project_id == project.id, Checkpoint.sha == sha)):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    try:
        return await store_for(settings, project).diff(sha)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/checkpoints/{sha}/restore", status_code=status.HTTP_202_ACCEPTED)
async def restore(project_id: uuid.UUID, sha: str, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    checkpoint = await db.scalar(select(Checkpoint).where(Checkpoint.project_id == project.id, Checkpoint.sha == sha))
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return run_view(await start(db, project, principal, "restore", f"Restore {checkpoint.message}", restore_sha=_effective(checkpoint), action="restore"))


@router.post("/undo", status_code=status.HTTP_202_ACCEPTED)
async def undo(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    target = _undo_target(await _history(db, project))
    if not target:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    return run_view(await start(db, project, principal, "restore", "Undo", restore_sha=target[0], undo_of=target[1], action="undo"))


@router.post("/redo", status_code=status.HTTP_202_ACCEPTED)
async def redo(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    target = _redo_target(await _history(db, project))
    if not target:
        raise HTTPException(status_code=409, detail="Nothing to redo")
    return run_view(await start(db, project, principal, "restore", "Redo", restore_sha=target, action="redo"))


# -- schema and routes ------------------------------------------------------------------------


@router.get("/schema")
async def schema(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    if not project.spec:
        return {"entities": [], "migrations": [], "auth": False, "has_api": False}
    spec = AppSpec.model_validate(project.spec)
    entities = [{"name": e.name, "label": e.label, "table": e.table, "description": e.description, "fields": [f.model_dump() for f in e.fields]} for e in spec.entities]
    return {"entities": entities, "migrations": project.migrations or [], "auth": spec.auth, "has_api": "api" in spec.targets}


@router.get("/routes")
async def routes(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    if not project.spec:
        return {"routes": [], "docs_url": None}
    spec = AppSpec.model_validate(project.spec)
    if "api" not in spec.targets:
        return {"routes": [], "docs_url": None}
    rows = [{"method": "GET", "path": "/api/health", "summary": "Health check", "auth": False}]
    if spec.auth:
        rows += [
            {"method": "POST", "path": "/api/auth/register", "summary": "Create an account", "auth": False},
            {"method": "POST", "path": "/api/auth/login", "summary": "Sign in and receive a token", "auth": False},
            {"method": "GET", "path": "/api/auth/me", "summary": "Current user", "auth": True},
        ]
    for e in spec.entities:
        base = f"/api/{e.slug}"
        rows += [
            {"method": "GET", "path": base, "summary": f"List {e.label.lower()}", "auth": spec.auth},
            {"method": "POST", "path": base, "summary": f"Create a {e.name}", "auth": spec.auth},
            {"method": "GET", "path": f"{base}/{{id}}", "summary": f"Get a {e.name}", "auth": spec.auth},
            {"method": "PUT", "path": f"{base}/{{id}}", "summary": f"Update a {e.name}", "auth": spec.auth},
            {"method": "DELETE", "path": f"{base}/{{id}}", "summary": f"Delete a {e.name}", "auth": spec.auth},
        ]
    docs = f"{preview.url_for(settings, project.preview_token)}api/docs" if project.preview_token and preview.current(settings, project.preview_token) else None
    return {"routes": rows, "docs_url": docs}


@router.post("/preview/reset-data")
async def reset_preview_data(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if not project.preview_token:
        raise HTTPException(status_code=409, detail="This project has no preview yet")
    await preview.reset_data(settings, project.preview_token)
    audit(db, principal, "builder.preview.reset", "project", str(project.id))
    await db.commit()
    return {"reset": True}


# -- approvals --------------------------------------------------------------------------------


@router.get("/approvals")
async def list_approvals(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    rows = await db.scalars(select(Approval).where(Approval.project_id == project.id).order_by(Approval.created_at.desc()).limit(50))
    return [approval_view(a) for a in rows]


@router.post("/approvals/{approval_id}/decision")
async def decide(
    project_id: uuid.UUID, approval_id: uuid.UUID, data: DecisionInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)
) -> dict:
    project, role = await project_access(db, project_id, principal, write=True)
    approval = await db.scalar(select(Approval).where(Approval.id == approval_id, Approval.project_id == project.id))
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="This request was already decided")
    if approval.kind.startswith("production") and role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can approve production changes")
    if data.decision == "approve" and approval.kind.startswith("production") and data.confirm != project.name:
        raise HTTPException(status_code=422, detail="Type the project name to approve a production change")
    approval.status = "approved" if data.decision == "approve" else "rejected"
    approval.decided_by = principal.user_id
    approval.decided_at = now()
    audit(db, principal, f"approval.{approval.status}", "approval", str(approval.id))
    result: dict = {"approval": None}
    if approval.kind == "destructive_migration":
        run = await db.get(GenerationRun, approval.run_id) if approval.run_id else None
        if run and run.status == "awaiting_approval":
            if approval.status == "approved":
                run.state = {**run.state, "approved": True, "resume_at": "plan", "outcome": None}
                run.status = "queued"
                project.generation_status = "building"
                await db.commit()
                pipeline.launch(run.id)
            else:
                run.status = "cancelled"
                run.finished_at = now()
                run.error = "The destructive change was rejected"
                await db.commit()
        else:
            await db.commit()
    else:
        deployment = await db.scalar(select(Deployment).where(Deployment.approval_id == approval.id))
        if deployment and approval.status == "approved":
            await db.commit()
            await _execute_deployment(db, settings, project, deployment)
        elif deployment:
            deployment.status = "rejected"
            deployment.finished_at = now()
            await db.commit()
        result["deployment"] = deployment_view(deployment) if deployment else None
    await db.refresh(approval)
    result["approval"] = approval_view(approval)
    return result


# -- GitHub -----------------------------------------------------------------------------------


def _sync_error(exc: github.SyncError) -> HTTPException:
    return HTTPException(status_code=409, detail={"message": str(exc), "conflicts": exc.conflicts})


@router.get("/github")
async def github_status(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    info = {"repo": project.github_repo, "branch": project.github_default_branch, "mode": github.mode(settings), "last_pushed_sha": project.last_pushed_sha, "last_pulled_sha": project.last_pulled_sha}
    if not project.github_repo or not store_for(settings, project).exists:
        return info
    try:
        target = await github.remote(settings, project.github_repo, project.github_installation_id)
        info |= await github.status(store_for(settings, project), target, project.github_default_branch)
    except github.SyncError as exc:
        info["error"] = str(exc)
    if info["mode"] == "local":
        info["clone_url"] = str(github.local_remote(settings, project.github_repo))
    else:
        info["clone_url"] = f"https://github.com/{project.github_repo}.git"
    return info


@router.post("/github/connect")
async def github_connect(project_id: uuid.UUID, data: GitHubConnectInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, role = await project_access(db, project_id, principal, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can connect a repository")
    try:
        github.validate(data.repo, data.branch)
    except github.SyncError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if github.mode(settings) == "local":
        await github.ensure_local_remote(settings, data.repo, data.branch)
    elif not data.installation_id:
        raise HTTPException(status_code=422, detail="Install the Omniweb GitHub App on the repository and include its installation ID")
    project.github_repo = data.repo
    project.github_default_branch = data.branch
    project.github_installation_id = data.installation_id
    audit(db, principal, "github.connect", "project", str(project.id))
    await db.commit()
    return await github_status(project_id, db, principal, settings)


@router.delete("/github", status_code=status.HTTP_204_NO_CONTENT)
async def github_disconnect(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> Response:
    project, role = await project_access(db, project_id, principal, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can disconnect a repository")
    project.github_repo = None
    project.github_installation_id = None
    audit(db, principal, "github.disconnect", "project", str(project.id))
    await db.commit()
    return Response(status_code=204)


@router.post("/github/push")
async def github_push(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if not project.github_repo:
        raise HTTPException(status_code=409, detail="Connect a GitHub repository first")
    if await active_run(db, project):
        raise HTTPException(status_code=409, detail="Wait for the current build to finish")
    try:
        target = await github.remote(settings, project.github_repo, project.github_installation_id)
        result = await github.push(store_for(settings, project), target, project.github_default_branch)
    except github.SyncError as exc:
        raise _sync_error(exc) from exc
    project.last_pushed_sha = result["pushed"]
    audit(db, principal, "github.push", "project", str(project.id))
    await db.commit()
    return result


@router.post("/github/pull")
async def github_pull(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if not project.github_repo:
        raise HTTPException(status_code=409, detail="Connect a GitHub repository first")
    if await active_run(db, project):
        raise HTTPException(status_code=409, detail="Wait for the current build to finish")
    store = store_for(settings, project)
    await store.init(project.github_default_branch)
    try:
        target = await github.remote(settings, project.github_repo, project.github_installation_id)
        result = await github.pull(store, target, project.github_default_branch)
    except github.SyncError as exc:
        raise _sync_error(exc) from exc
    audit(db, principal, "github.pull", "project", str(project.id))
    if result.get("merged"):
        sha = result["sha"]
        db.add(Checkpoint(project_id=project.id, sha=sha, parent_sha=project.head_sha, message=result["message"], author="user", spec=project.spec, migrations=project.migrations))
        project.head_sha = sha
        project.last_pulled_sha = sha
        await db.commit()
        if project.spec:
            result["run"] = run_view(await start(db, project, principal, "verify", "Check changes pulled from GitHub"))
    else:
        await db.commit()
    return result


# -- deployments ------------------------------------------------------------------------------


@router.get("/deployments")
async def list_deployments(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    rows = await db.scalars(select(Deployment).where(Deployment.project_id == project.id).order_by(Deployment.created_at.desc()).limit(30))
    return [deployment_view(d) for d in rows]


@router.post("/deployments/estimate")
async def estimate_deployment(project_id: uuid.UUID, data: DeployInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal)
    if not project.spec:
        raise HTTPException(status_code=409, detail="Generate the app first")
    spec = AppSpec.model_validate(project.spec)
    return {"environment": data.environment, "region": data.region, **deploy.estimate(spec, data.environment)}


@router.post("/deployments", status_code=status.HTTP_201_CREATED)
async def request_deployment(project_id: uuid.UUID, data: DeployInput, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if not project.spec or not project.head_sha:
        raise HTTPException(status_code=409, detail="Generate the app first")
    if not (project.last_build or {}).get("ok") or (project.last_build or {}).get("sha") != project.head_sha:
        raise HTTPException(status_code=409, detail="The latest commit hasn't passed its checks. Fix the build before deploying.")
    if not project.github_repo or project.last_pushed_sha != project.head_sha:
        raise HTTPException(status_code=409, detail="App Platform builds from GitHub. Push the latest commit before deploying.")
    if data.region not in deploy.REGIONS:
        raise HTTPException(status_code=422, detail="Unknown App Platform region")
    query = select(CloudConnection).where(CloudConnection.organization_id == project.organization_id, CloudConnection.provider == "digitalocean")
    if data.cloud_connection_id:
        query = query.where(CloudConnection.id == data.cloud_connection_id)
    connection = await db.scalar(query.order_by(CloudConnection.created_at))
    if not connection:
        raise HTTPException(status_code=409, detail="Connect a DigitalOcean account in Settings → Cloud accounts first")
    spec = AppSpec.model_validate(project.spec)
    try:
        app_spec = deploy.prepare(spec, project.github_repo, project.github_default_branch, data.region, data.environment)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cost = deploy.estimate(spec, data.environment)
    kind = "production_deployment" if data.environment == "production" else "deployment"
    approval = Approval(
        project_id=project.id,
        organization_id=project.organization_id,
        kind=kind,
        summary=f"Deploy {project.head_sha[:7]} to {data.environment} on App Platform ({deploy.REGIONS[data.region]}) — about ${cost['monthly_usd']:.2f}/month",
        details={"app_spec": app_spec, "estimate": cost, "connection": connection.label, "mock": settings.mock_infrastructure},
        estimated_monthly_usd=cost["monthly_usd"],
        requested_by=f"user:{principal.user_id}",
    )
    db.add(approval)
    await db.flush()
    deployment = Deployment(
        project_id=project.id,
        organization_id=project.organization_id,
        environment=data.environment,
        cloud_connection_id=connection.id,
        commit_sha=project.head_sha,
        region=data.region,
        approval_id=approval.id,
        estimated_monthly_usd=cost["monthly_usd"],
        app_spec=app_spec,
        requested_by=principal.user_id,
        log=[{"at": now().isoformat(), "message": "Prepared App Platform spec; waiting for approval"}],
    )
    db.add(deployment)
    audit(db, principal, "deployment.request", "project", str(project.id))
    await db.commit()
    return {"deployment": deployment_view(deployment), "approval": approval_view(approval)}


async def _previous_live(db: AsyncSession, project: Project, environment: str, exclude: uuid.UUID | None = None) -> Deployment | None:
    query = select(Deployment).where(Deployment.project_id == project.id, Deployment.environment == environment, Deployment.status == "live", Deployment.external_app_id.is_not(None))
    if exclude:
        query = query.where(Deployment.id != exclude)
    return await db.scalar(query.order_by(Deployment.created_at.desc()))


async def _execute_deployment(db: AsyncSession, settings: Settings, project: Project, deployment: Deployment) -> None:
    connection = await db.get(CloudConnection, deployment.cloud_connection_id)
    previous = await _previous_live(db, project, deployment.environment, deployment.id)
    deployment.status = "deploying"
    log = list(deployment.log) + [{"at": now().isoformat(), "message": "Approved; sending spec to App Platform" + (" (mock infrastructure — nothing is created)" if settings.mock_infrastructure else "")}]
    deployment.log = log
    await db.commit()
    try:
        token = decrypt_secret(connection.encrypted_token, settings)
        if deployment.rollback_of:
            target = await db.get(Deployment, deployment.rollback_of)
            result = await deploy.rollback(settings, token, target.external_app_id, target.external_deployment_id)
            deployment.external_app_id = target.external_app_id
        else:
            result = await deploy.execute(settings, token, deployment.app_spec, previous.external_app_id if previous else None)
            deployment.external_app_id = result["app_id"]
        del token
        deployment.external_deployment_id = result["deployment_id"]
        deployment.url = result.get("url")
        deployment.status = "live" if result.get("phase") in {"ACTIVE", None} or result.get("mock") else "deploying"
        log.append({"at": now().isoformat(), "message": f"App Platform deployment {result['deployment_id']} is {result.get('phase') or 'queued'}"})
        if previous and deployment.status == "live":
            previous.status = "superseded"
        project.deployment_status = f"{deployment.environment}_live" if deployment.status == "live" else "deploying"
    except (DigitalOceanError, ValueError) as exc:
        deployment.status = "failed"
        log.append({"at": now().isoformat(), "message": f"App Platform rejected the deployment: {exc}"})
    deployment.log = list(log)
    deployment.finished_at = now()
    await db.commit()


@router.post("/deployments/{deployment_id}/rollback", status_code=status.HTTP_201_CREATED)
async def request_rollback(project_id: uuid.UUID, deployment_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    target = await db.scalar(select(Deployment).where(Deployment.id == deployment_id, Deployment.project_id == project.id))
    if not target or not target.external_deployment_id or target.status not in {"live", "superseded"}:
        raise HTTPException(status_code=409, detail="Only a deployment that was live can be rolled back to")
    kind = "production_rollback" if target.environment == "production" else "rollback"
    approval = Approval(
        project_id=project.id,
        organization_id=project.organization_id,
        kind=kind,
        summary=f"Roll {target.environment} back to {target.commit_sha[:7]}",
        details={"target_deployment": str(target.id)},
        estimated_monthly_usd=target.estimated_monthly_usd,
        requested_by=f"user:{principal.user_id}",
    )
    db.add(approval)
    await db.flush()
    rollback = Deployment(
        project_id=project.id,
        organization_id=project.organization_id,
        environment=target.environment,
        cloud_connection_id=target.cloud_connection_id,
        commit_sha=target.commit_sha,
        region=target.region,
        approval_id=approval.id,
        estimated_monthly_usd=target.estimated_monthly_usd,
        rollback_of=target.id,
        app_spec=target.app_spec,
        requested_by=principal.user_id,
        log=[{"at": now().isoformat(), "message": f"Rollback to {target.commit_sha[:7]} prepared; waiting for approval"}],
    )
    db.add(rollback)
    audit(db, principal, "deployment.rollback.request", "project", str(project.id))
    await db.commit()
    return {"deployment": deployment_view(rollback), "approval": approval_view(approval)}
