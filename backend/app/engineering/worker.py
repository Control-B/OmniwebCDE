import asyncio
import base64
import hashlib
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..intelligence_models import (
    CapabilityEdge,
    DesignRequirement,
    DesignRevision,
    EngineeringArtifact,
    EngineeringDesign,
    EngineeringJob,
)
from ..services.assets import AssetStore
from . import service

_running: dict[uuid.UUID, asyncio.Task] = {}
_semaphore: asyncio.Semaphore | None = None


def semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().engineering_max_concurrent_jobs)
    return _semaphore


async def execute(job_id: uuid.UUID) -> None:
    settings = get_settings()
    started = time.monotonic()
    async with semaphore():
        async with SessionLocal() as db:
            job = await db.get(EngineeringJob, job_id)
            if not job or job.status not in {"queued", "running"}:
                return
            revision = await db.get(DesignRevision, job.revision_id)
            requirement = await db.scalar(
                select(DesignRequirement).where(DesignRequirement.revision_id == revision.id)
            )
            design = await db.get(EngineeringDesign, job.design_id)
            job.status = "running"
            job.started_at = datetime.now(UTC)
            job.attempts += 1
            revision.status = "generating"
            await db.commit()
            body = {
                "design_id": str(design.id),
                "revision": revision.revision,
                "requirements": requirement.normalized,
            }
        try:
            result = await service.generate(settings, body)
            artifacts = []
            total_bytes = 0
            for payload in result["artifacts"]:
                data = base64.b64decode(payload["data_base64"], validate=True)
                digest = hashlib.sha256(data).hexdigest()
                if digest != payload["sha256"] or len(data) != payload["size"]:
                    raise ValueError("CAD worker artifact integrity check failed")
                total_bytes += len(data)
                if total_bytes > settings.engineering_max_artifact_bytes:
                    raise ValueError("Engineering artifact budget exceeded")
                location, stored_digest = AssetStore(settings).put(
                    design.organization_id, data, payload["format"]
                )
                if stored_digest != digest:
                    raise ValueError("Stored engineering artifact digest mismatch")
                artifacts.append((payload, location))

            async with SessionLocal() as db:
                job = await db.get(EngineeringJob, job_id)
                revision = await db.get(DesignRevision, job.revision_id)
                design = await db.get(EngineeringDesign, job.design_id)
                revision.status = result["status"]
                revision.operations = result["operations"]
                revision.geometry = result["geometry"]
                revision.preview_mesh = result["preview"]
                revision.validation_level = result["validation_level"]
                revision.validation_checks = result["checks"]
                revision.safety_notice = result["safety_notice"]
                for payload, location in artifacts:
                    artifact = EngineeringArtifact(
                        revision_id=revision.id,
                        organization_id=job.organization_id,
                        kind=payload["kind"],
                        format=payload["format"],
                        filename=payload["filename"][:240],
                        media_type=payload["media_type"][:100],
                        storage_location=location,
                        sha256=payload["sha256"],
                        size=payload["size"],
                    )
                    db.add(artifact)
                    await db.flush()
                    db.add(
                        CapabilityEdge(
                            organization_id=job.organization_id,
                            source_type="engineering_revision",
                            source_id=revision.id,
                            relation="generated",
                            target_type="engineering_artifact",
                            target_id=artifact.id,
                            metadata_json={"format": artifact.format},
                        )
                    )
                job.status = "completed" if result["status"] == "validated" else "failed"
                job.duration_seconds = round(time.monotonic() - started, 6)
                job.finished_at = datetime.now(UTC)
                design.status = "geometrically_validated" if result["status"] == "validated" else "invalid"
                await db.commit()
        except Exception as exc:
            async with SessionLocal() as db:
                job = await db.get(EngineeringJob, job_id)
                if job:
                    revision = await db.get(DesignRevision, job.revision_id)
                    design = await db.get(EngineeringDesign, job.design_id)
                    job.status = (
                        "dead_letter"
                        if job.attempts >= settings.engineering_max_job_attempts
                        else "failed"
                    )
                    job.error = str(exc)[:500]
                    job.duration_seconds = round(time.monotonic() - started, 6)
                    job.finished_at = datetime.now(UTC)
                    revision.status = "failed"
                    design.status = "needs_attention"
                    await db.commit()
        finally:
            _running.pop(job_id, None)


def launch(job_id: uuid.UUID) -> None:
    task = _running.get(job_id)
    if not task or task.done():
        _running[job_id] = asyncio.create_task(execute(job_id))


def cancel(job_id: uuid.UUID) -> None:
    task = _running.get(job_id)
    if task and not task.done():
        task.cancel()


async def resume_all() -> None:
    async with SessionLocal() as db:
        jobs = list(
            await db.scalars(
                select(EngineeringJob).where(EngineeringJob.status.in_(["queued", "running"]))
            )
        )
        for job in jobs:
            job.status = "queued"
        await db.commit()
    for job in jobs:
        launch(job.id)


async def stop_all() -> None:
    tasks = list(_running.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _running.clear()
