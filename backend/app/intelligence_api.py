"""Unified Create, business plans, content assets and media jobs."""

import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_db
from .intelligence import orchestrator
from .intelligence_models import (
    AssetVersion,
    BusinessPlan,
    BusinessPlanSection,
    ContentAsset,
    IntelligenceTask,
    IntelligenceWorkflow,
    MediaJob,
    PlanClaim,
)
from .projects_api import audit, project_access
from .schemas import Principal
from .security import get_principal, require_admin
from .services.assets import AssetStore
from .services.media import MediaError, providers

router = APIRouter(prefix="/api/v1")


class CreateInput(BaseModel):
    prompt: str = Field(min_length=3, max_length=20_000)
    mode: Literal["AUTO", "BUILD", "BUSINESS", "MARKETING", "CONTENT", "IMAGE", "VIDEO"] = "AUTO"
    project_id: uuid.UUID | None = None
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")
    context: dict = Field(default_factory=dict)


def workflow_view(workflow: IntelligenceWorkflow, tasks: list[IntelligenceTask]) -> dict:
    return {
        "id": str(workflow.id),
        "project_id": str(workflow.project_id) if workflow.project_id else None,
        "mode": workflow.mode,
        "prompt": workflow.prompt,
        "status": workflow.status,
        "total_cost_usd": workflow.total_cost_usd,
        "result": workflow.result,
        "created_at": workflow.created_at.isoformat(),
        "finished_at": workflow.finished_at.isoformat() if workflow.finished_at else None,
        "tasks": [
            {
                "id": str(task.id),
                "key": task.key,
                "kind": task.kind,
                "title": task.title,
                "status": task.status,
                "depends_on": task.depends_on,
                "output": task.output,
                "error": task.error,
            }
            for task in tasks
        ],
    }


async def owned_workflow(
    db: AsyncSession, principal: Principal, workflow_id: uuid.UUID
) -> IntelligenceWorkflow:
    row = await db.scalar(
        select(IntelligenceWorkflow).where(
            IntelligenceWorkflow.id == workflow_id,
            IntelligenceWorkflow.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if row.project_id:
        await project_access(db, row.project_id, principal)
    return row


@router.post("/intelligence/requests", status_code=status.HTTP_202_ACCEPTED)
async def unified_create(
    data: CreateInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    if data.project_id:
        await project_access(db, data.project_id, principal, write=True)
    existing = await db.scalar(
        select(IntelligenceWorkflow).where(
            IntelligenceWorkflow.organization_id == principal.organization_id,
            IntelligenceWorkflow.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        tasks = list(
            await db.scalars(
                select(IntelligenceTask)
                .where(IntelligenceTask.workflow_id == existing.id)
                .order_by(IntelligenceTask.position)
            )
        )
        return workflow_view(existing, tasks)
    intents = orchestrator.detect_intents(data.prompt, data.mode)
    workflow = IntelligenceWorkflow(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        requested_by=principal.user_id,
        mode=data.mode,
        prompt=data.prompt,
        idempotency_key=data.idempotency_key,
        context=data.context,
    )
    db.add(workflow)
    await db.flush()
    tasks = []
    for position, definition in enumerate(orchestrator.dependency_graph(intents)):
        task = IntelligenceTask(
            workflow_id=workflow.id,
            organization_id=principal.organization_id,
            position=position,
            **definition,
        )
        db.add(task)
        tasks.append(task)
    audit(db, principal, "intelligence.workflow.create", "workflow", str(workflow.id))
    await db.commit()
    orchestrator.launch(workflow.id)
    return workflow_view(workflow, tasks)


@router.get("/intelligence/requests")
async def list_workflows(
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    query = (
        select(IntelligenceWorkflow)
        .where(IntelligenceWorkflow.organization_id == principal.organization_id)
        .order_by(IntelligenceWorkflow.created_at.desc())
        .limit(50)
    )
    if project_id:
        await project_access(db, project_id, principal)
        query = query.where(IntelligenceWorkflow.project_id == project_id)
    elif principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Choose a project")
    result = []
    for workflow in await db.scalars(query):
        tasks = list(
            await db.scalars(
                select(IntelligenceTask)
                .where(IntelligenceTask.workflow_id == workflow.id)
                .order_by(IntelligenceTask.position)
            )
        )
        result.append(workflow_view(workflow, tasks))
    return result


@router.get("/intelligence/requests/{workflow_id}")
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    workflow = await owned_workflow(db, principal, workflow_id)
    tasks = list(
        await db.scalars(
            select(IntelligenceTask)
            .where(IntelligenceTask.workflow_id == workflow.id)
            .order_by(IntelligenceTask.position)
        )
    )
    return workflow_view(workflow, tasks)


# Content library -------------------------------------------------------------------------------


def asset_view(asset: ContentAsset, version: AssetVersion | None = None) -> dict:
    return {
        "id": str(asset.id),
        "project_id": str(asset.project_id) if asset.project_id else None,
        "campaign_id": str(asset.campaign_id) if asset.campaign_id else None,
        "content_type": asset.content_type,
        "title": asset.title,
        "status": asset.status,
        "current_version": asset.current_version,
        "prompt_reference": asset.prompt_reference,
        "provider": asset.provider,
        "model": asset.model,
        "cost_usd": asset.cost_usd,
        "storage_location": asset.storage_location,
        "usage_rights": asset.usage_rights,
        "metadata": asset.metadata_json,
        "content": version.content if version else None,
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


async def owned_asset(db: AsyncSession, principal: Principal, asset_id: uuid.UUID) -> ContentAsset:
    asset = await db.scalar(
        select(ContentAsset).where(
            ContentAsset.id == asset_id,
            ContentAsset.organization_id == principal.organization_id,
        )
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.project_id:
        await project_access(db, asset.project_id, principal)
    return asset


@router.get("/assets")
async def list_assets(
    project_id: uuid.UUID | None = None,
    content_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    query = (
        select(ContentAsset)
        .where(ContentAsset.organization_id == principal.organization_id)
        .order_by(ContentAsset.updated_at.desc())
        .limit(200)
    )
    if project_id:
        await project_access(db, project_id, principal)
        query = query.where(ContentAsset.project_id == project_id)
    elif principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Choose a project")
    if content_type:
        query = query.where(ContentAsset.content_type == content_type)
    return [asset_view(asset) for asset in await db.scalars(query)]


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    asset = await owned_asset(db, principal, asset_id)
    version = await db.scalar(
        select(AssetVersion).where(
            AssetVersion.asset_id == asset.id,
            AssetVersion.version == asset.current_version,
        )
    )
    result = asset_view(asset, version)
    result["versions"] = [
        {
            "version": row.version,
            "change_note": row.change_note,
            "content_hash": row.content_hash,
            "created_at": row.created_at.isoformat(),
        }
        for row in await db.scalars(
            select(AssetVersion)
            .where(AssetVersion.asset_id == asset.id)
            .order_by(AssetVersion.version.desc())
        )
    ]
    return result


class AssetCreate(BaseModel):
    project_id: uuid.UUID | None = None
    content_type: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=2_000_000)
    usage_rights: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def create_asset(
    data: AssetCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    if data.project_id:
        await project_access(db, data.project_id, principal, write=True)
    asset = ContentAsset(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        content_type=data.content_type,
        title=data.title,
        usage_rights=data.usage_rights,
        metadata_json=data.metadata,
        created_by=principal.user_id,
    )
    db.add(asset)
    await db.flush()
    version = AssetVersion(
        asset_id=asset.id,
        organization_id=principal.organization_id,
        version=1,
        content=data.content,
        content_hash=hashlib.sha256(data.content.encode()).hexdigest(),
        change_note="Created",
        created_by=principal.user_id,
    )
    db.add(version)
    audit(db, principal, "asset.create", "asset", str(asset.id))
    await db.commit()
    return asset_view(asset, version)


class AssetEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str = Field(max_length=2_000_000)
    change_note: str = Field(default="Edited", max_length=300)


@router.post("/assets/{asset_id}/versions", status_code=status.HTTP_201_CREATED)
async def edit_asset(
    asset_id: uuid.UUID,
    data: AssetEdit,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    asset = await owned_asset(db, principal, asset_id)
    asset.current_version += 1
    if data.title:
        asset.title = data.title
    version = AssetVersion(
        asset_id=asset.id,
        organization_id=principal.organization_id,
        version=asset.current_version,
        content=data.content,
        content_hash=hashlib.sha256(data.content.encode()).hexdigest(),
        change_note=data.change_note,
        created_by=principal.user_id,
    )
    db.add(version)
    audit(db, principal, "asset.version.create", "asset", str(asset.id))
    await db.commit()
    return asset_view(asset, version)


@router.get("/assets/{asset_id}/export")
async def export_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Response:
    asset = await owned_asset(db, principal, asset_id)
    version = await db.scalar(
        select(AssetVersion).where(
            AssetVersion.asset_id == asset.id,
            AssetVersion.version == asset.current_version,
        )
    )
    if version and version.content is not None:
        return Response(
            version.content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{asset.id}.txt"'},
        )
    if asset.storage_location:
        return Response(
            AssetStore(get_settings()).read(principal.organization_id, asset.storage_location),
            media_type="application/octet-stream",
        )
    raise HTTPException(status_code=404, detail="Asset has no exportable content")


# Business plans --------------------------------------------------------------------------------


@router.get("/business-plans")
async def list_business_plans(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(BusinessPlan)
        .where(
            BusinessPlan.organization_id == principal.organization_id,
            BusinessPlan.project_id == project_id,
        )
        .order_by(BusinessPlan.updated_at.desc())
    )
    return [
        {
            "id": str(plan.id),
            "title": plan.title,
            "status": plan.status,
            "version": plan.version,
            "assumptions": plan.assumptions,
            "scenarios": plan.scenarios,
            "updated_at": plan.updated_at.isoformat(),
        }
        for plan in rows
    ]


@router.get("/business-plans/{plan_id}")
async def get_business_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    plan = await db.scalar(
        select(BusinessPlan).where(
            BusinessPlan.id == plan_id,
            BusinessPlan.organization_id == principal.organization_id,
        )
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Business plan not found")
    await project_access(db, plan.project_id, principal)
    sections = list(
        await db.scalars(
            select(BusinessPlanSection)
            .where(BusinessPlanSection.plan_id == plan.id)
            .order_by(BusinessPlanSection.position)
        )
    )
    claims = list(await db.scalars(select(PlanClaim).where(PlanClaim.plan_id == plan.id)))
    by_section: dict[uuid.UUID, list] = {}
    for claim in claims:
        by_section.setdefault(claim.section_id, []).append(
            {
                "id": str(claim.id),
                "claim": claim.claim,
                "evidence_type": claim.evidence_type,
                "source_url": claim.source_url,
                "source_title": claim.source_title,
            }
        )
    return {
        "id": str(plan.id),
        "project_id": str(plan.project_id),
        "title": plan.title,
        "status": plan.status,
        "version": plan.version,
        "assumptions": plan.assumptions,
        "scenarios": plan.scenarios,
        "sections": [
            {
                "id": str(section.id),
                "key": section.key,
                "title": section.title,
                "content": section.content,
                "claims": by_section.get(section.id, []),
            }
            for section in sections
        ],
    }


class PlanSectionEdit(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    content: str = Field(max_length=200_000)


@router.put("/business-plans/{plan_id}/sections/{section_id}")
async def edit_plan_section(
    plan_id: uuid.UUID,
    section_id: uuid.UUID,
    data: PlanSectionEdit,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    plan = await db.scalar(
        select(BusinessPlan).where(
            BusinessPlan.id == plan_id,
            BusinessPlan.organization_id == principal.organization_id,
        )
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Business plan not found")
    await project_access(db, plan.project_id, principal, write=True)
    section = await db.get(BusinessPlanSection, section_id)
    if not section or section.plan_id != plan.id:
        raise HTTPException(status_code=404, detail="Section not found")
    section.content = data.content
    section.title = data.title or section.title
    plan.version += 1
    audit(db, principal, "business_plan.section.update", "business_plan", str(plan.id))
    await db.commit()
    return {
        "id": str(section.id),
        "title": section.title,
        "content": section.content,
        "plan_version": plan.version,
    }


# Media ------------------------------------------------------------------------------------------


@router.get("/media/capabilities")
async def media_capabilities(
    settings: Settings = Depends(get_settings),
    _: Principal = Depends(get_principal),
) -> list[dict]:
    return [
        capability.__dict__
        for capability in (adapter.capabilities() for adapter in providers(settings).values())
    ]


def media_view(job: MediaJob) -> dict:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "provider": job.provider,
        "model": job.model,
        "operation": job.operation,
        "status": job.status,
        "asset_id": str(job.asset_id) if job.asset_id else None,
        "estimated_cost_usd": job.estimated_cost_usd,
        "actual_cost_usd": job.actual_cost_usd,
        "error": job.error,
        "request": {k: v for k, v in job.request.items() if not k.startswith("_")},
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


async def owned_media_job(db: AsyncSession, principal: Principal, job_id: uuid.UUID) -> MediaJob:
    job = await db.scalar(
        select(MediaJob).where(
            MediaJob.id == job_id,
            MediaJob.organization_id == principal.organization_id,
        )
    )
    if not job:
        raise HTTPException(status_code=404, detail="Media job not found")
    if job.project_id:
        await project_access(db, job.project_id, principal)
    return job


@router.get("/media/jobs")
async def list_media_jobs(
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    query = (
        select(MediaJob)
        .where(MediaJob.organization_id == principal.organization_id)
        .order_by(MediaJob.created_at.desc())
        .limit(100)
    )
    if project_id:
        await project_access(db, project_id, principal)
        query = query.where(MediaJob.project_id == project_id)
    elif principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Choose a project")
    return [media_view(job) for job in await db.scalars(query)]


@router.post("/media/jobs/{job_id}/authorize")
async def authorize_media_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    job = await owned_media_job(db, principal, job_id)
    if job.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"Job is {job.status}")
    adapter = providers(settings).get(job.provider)
    if not adapter:
        raise HTTPException(status_code=409, detail="Provider unavailable")
    try:
        submitted = await adapter.submit(job.kind, job.model, job.operation, job.request)
    except MediaError as exc:
        job.status = "failed"
        job.error = str(exc)
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    job.status = submitted.status
    job.provider_job_id = submitted.provider_job_id
    if submitted.data:
        location, digest = AssetStore(settings).put(
            principal.organization_id,
            submitted.data,
            submitted.extension or "bin",
        )
        asset = ContentAsset(
            organization_id=principal.organization_id,
            project_id=job.project_id,
            campaign_id=job.campaign_id,
            content_type=job.kind,
            title=str(job.request.get("prompt") or f"Generated {job.kind}")[:200],
            status="draft",
            provider=job.provider,
            model=job.model,
            cost_usd=job.actual_cost_usd,
            storage_location=location,
            usage_rights={"status": "provider_terms_apply"},
            metadata_json={
                "sha256": digest,
                "request": {k: v for k, v in job.request.items() if not k.startswith("_")},
            },
            created_by=principal.user_id,
        )
        db.add(asset)
        await db.flush()
        job.asset_id = asset.id
    audit(db, principal, "media.job.authorize", "media_job", str(job.id))
    await db.commit()
    return media_view(job)


@router.post("/media/jobs/{job_id}/refresh")
async def refresh_media_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    job = await owned_media_job(db, principal, job_id)
    if not job.provider_job_id or job.status in {"completed", "failed", "cancelled"}:
        return media_view(job)
    adapter = providers(settings).get(job.provider)
    try:
        update = await adapter.status(job.kind, job.provider_job_id)
    except MediaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    job.status = update.status
    if update.data:
        location, digest = AssetStore(settings).put(
            principal.organization_id,
            update.data,
            update.extension or "bin",
        )
        asset = ContentAsset(
            organization_id=principal.organization_id,
            project_id=job.project_id,
            campaign_id=job.campaign_id,
            content_type=job.kind,
            title=str(job.request.get("prompt") or f"Generated {job.kind}")[:200],
            status="draft",
            provider=job.provider,
            model=job.model,
            storage_location=location,
            usage_rights={"status": "provider_terms_apply"},
            metadata_json={"sha256": digest},
            created_by=principal.user_id,
        )
        db.add(asset)
        await db.flush()
        job.asset_id = asset.id
    await db.commit()
    return media_view(job)


@router.post("/media/jobs/{job_id}/cancel")
async def cancel_media_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    job = await owned_media_job(db, principal, job_id)
    if job.status in {"completed", "failed", "cancelled"}:
        return media_view(job)
    if job.provider_job_id:
        adapter = providers(settings).get(job.provider)
        try:
            await adapter.cancel(job.kind, job.provider_job_id)
        except MediaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    job.status = "cancelled"
    await db.commit()
    return media_view(job)
