"""Tenant-scoped, content-addressed artifact storage.

Artifacts are untrusted data. They are stored per tenant, and references are resolved
only within the caller's tenant, so one tenant can never read another's files.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .contracts import ArtifactInput
from .models import Artifact
from .validation_engine import safe_relative


def _root(settings: Settings, tenant_id: uuid.UUID) -> Path:
    root = Path(settings.data_dir).resolve() / "artifacts" / str(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def put(db: AsyncSession, settings: Settings, tenant_id: uuid.UUID, task_id: uuid.UUID, kind: str, path: str, content: str) -> Artifact:
    data = content.encode()
    if len(data) > settings.max_artifact_bytes:
        raise HTTPException(status_code=413, detail=f"Artifact {path} exceeds {settings.max_artifact_bytes} bytes")
    digest = hashlib.sha256(data).hexdigest()
    target = _root(settings, tenant_id) / digest
    if not target.exists():
        target.write_bytes(data)
    artifact = Artifact(tenant_id=tenant_id, task_id=task_id, kind=kind, path=path, sha256=digest, size=len(data))
    db.add(artifact)
    await db.flush()
    return artifact


def read(settings: Settings, artifact: Artifact) -> str:
    return (_root(settings, artifact.tenant_id) / artifact.sha256).read_bytes().decode(errors="replace")


async def store_inputs(db: AsyncSession, settings: Settings, tenant_id: uuid.UUID, task_id: uuid.UUID, inputs: list[ArtifactInput]) -> None:
    total = 0
    for item in inputs:
        if not safe_relative(item.path):
            raise HTTPException(status_code=422, detail=f"Artifact path is not a safe relative path: {item.path[:80]}")
        if item.content is None and item.artifact_id:
            source = await db.scalar(select(Artifact).where(Artifact.id == item.artifact_id, Artifact.tenant_id == tenant_id))
            if not source:
                raise HTTPException(status_code=404, detail="Unknown artifact reference")
            content = read(settings, source)
        else:
            content = item.content or ""
        total += len(content.encode())
        if total > settings.max_task_artifact_bytes:
            raise HTTPException(status_code=413, detail="Task artifacts exceed the size limit")
        await put(db, settings, tenant_id, task_id, "input", item.path, content)


async def working_set(db: AsyncSession, settings: Settings, tenant_id: uuid.UUID, task_id: uuid.UUID) -> dict[str, str]:
    """Input files overlaid with the latest repair-context files, by path."""
    files: dict[str, str] = {}
    rows = await db.scalars(
        select(Artifact)
        .where(Artifact.tenant_id == tenant_id, Artifact.task_id == task_id, Artifact.kind.in_(["input", "working"]))
        .order_by(Artifact.created_at)
    )
    for row in rows:
        files[row.path] = read(settings, row)
    return files
