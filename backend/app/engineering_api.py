import base64
import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_db
from .engineering import service, worker
from .intelligence_models import (
    AssemblyArtifact,
    AssemblyRevision,
    CapabilityEdge,
    DesignRequirement,
    DesignRevision,
    EngineeringArtifact,
    EngineeringAssembly,
    EngineeringDesign,
    EngineeringFeedback,
    EngineeringJob,
    EngineeringSimulation,
    ManufacturingEstimate,
)
from .models import Approval
from .projects_api import audit, project_access
from .schemas import Principal
from .security import get_principal, require_admin, signing_secret
from .services.assets import AssetStore

router = APIRouter(prefix="/api/v1/engineering", tags=["engineering"])
SAFETY_NOTICE = (
    "Geometry validation is not structural analysis, code compliance, engineering "
    "certification, or approval for manufacturing."
)
PARAMETERS = {
    "plate": {"length_mm", "width_mm", "thickness_mm"},
    "l_bracket": {"length_mm", "width_mm", "height_mm", "thickness_mm"},
    "spacer": {"outer_diameter_mm", "inner_diameter_mm", "length_mm"},
    "enclosure": {"length_mm", "width_mm", "height_mm", "wall_thickness_mm"},
}


class RequirementsInput(BaseModel):
    component_name: str = Field(min_length=2, max_length=160)
    component_kind: Literal["plate", "l_bracket", "spacer", "enclosure"]
    units: Literal["mm"] = "mm"
    material: str = Field(min_length=2, max_length=120)
    manufacturing_process: str | None = Field(default=None, max_length=160)
    parameters: dict[str, float]
    hole_count: int = Field(default=0, ge=0, le=100)
    hole_diameter_mm: float | None = Field(default=None, gt=0, le=1_000)
    tolerances: dict[str, float] = Field(default_factory=dict)
    requested_outputs: list[Literal["step", "stl", "pdf", "dxf", "source"]] = Field(
        default_factory=lambda: ["step", "stl", "pdf", "dxf", "source"]
    )
    standards: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("parameters")
    @classmethod
    def parameters_valid(cls, value: dict[str, float]) -> dict[str, float]:
        if any(number <= 0 or number > 100_000 for number in value.values()):
            raise ValueError("Dimensions must be positive and no greater than 100,000 mm")
        return value

    def missing(self) -> list[str]:
        missing = PARAMETERS[self.component_kind] - self.parameters.keys()
        if self.hole_count and not self.hole_diameter_mm:
            missing.add("hole_diameter_mm")
        return sorted(missing)


class DesignCreate(BaseModel):
    project_id: uuid.UUID
    prompt: str = Field(min_length=3, max_length=20_000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")


class RevisionCreate(BaseModel):
    requirements: RequirementsInput
    change_note: str = Field(min_length=3, max_length=500)
    source_prompt: str = Field(default="Manual parameter revision", max_length=20_000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")


async def owned_design(
    db: AsyncSession, principal: Principal, design_id: uuid.UUID, *, write: bool = False
) -> EngineeringDesign:
    design = await db.scalar(
        select(EngineeringDesign).where(
            EngineeringDesign.id == design_id,
            EngineeringDesign.organization_id == principal.organization_id,
        )
    )
    if not design:
        raise HTTPException(status_code=404, detail="Engineering design not found")
    await project_access(db, design.project_id, principal, write=write)
    return design


async def revision_view(db: AsyncSession, revision: DesignRevision) -> dict:
    requirement = await db.scalar(
        select(DesignRequirement).where(DesignRequirement.revision_id == revision.id)
    )
    artifacts = list(
        await db.scalars(
            select(EngineeringArtifact)
            .where(EngineeringArtifact.revision_id == revision.id)
            .order_by(EngineeringArtifact.format)
        )
    )
    job = await db.scalar(
        select(EngineeringJob)
        .where(EngineeringJob.revision_id == revision.id)
        .order_by(EngineeringJob.created_at.desc())
    )
    return {
        "id": str(revision.id),
        "revision": revision.revision,
        "status": revision.status,
        "approval_status": revision.approval_status,
        "change_note": revision.change_note,
        "requirements": requirement.normalized if requirement else {},
        "missing_critical": requirement.missing_critical if requirement else [],
        "assumptions": requirement.assumptions if requirement else [],
        "operations": revision.operations,
        "geometry": revision.geometry,
        "preview": revision.preview_mesh,
        "validation_level": revision.validation_level,
        "validation_checks": revision.validation_checks,
        "safety_notice": revision.safety_notice or SAFETY_NOTICE,
        "job": {
            "id": str(job.id),
            "status": job.status,
            "attempts": job.attempts,
            "error": job.error,
            "duration_seconds": job.duration_seconds,
        }
        if job
        else None,
        "artifacts": [
            {
                "id": str(artifact.id),
                "kind": artifact.kind,
                "format": artifact.format,
                "filename": artifact.filename,
                "media_type": artifact.media_type,
                "sha256": artifact.sha256,
                "size": artifact.size,
            }
            for artifact in artifacts
        ],
        "created_at": revision.created_at.isoformat(),
    }


async def design_view(db: AsyncSession, design: EngineeringDesign, detail: bool = False) -> dict:
    result = {
        "id": str(design.id),
        "project_id": str(design.project_id),
        "name": design.name,
        "component_kind": design.component_kind,
        "status": design.status,
        "current_revision": design.current_revision,
        "created_at": design.created_at.isoformat(),
        "updated_at": design.updated_at.isoformat(),
    }
    if detail:
        revisions = list(
            await db.scalars(
                select(DesignRevision)
                .where(DesignRevision.design_id == design.id)
                .order_by(DesignRevision.revision.desc())
            )
        )
        result["revisions"] = [await revision_view(db, revision) for revision in revisions]
    return result


async def create_revision_records(
    db: AsyncSession,
    principal: Principal,
    design: EngineeringDesign,
    requirements: dict,
    source_prompt: str,
    change_note: str,
    idempotency_key: str,
    missing: list[str] | None = None,
) -> tuple[DesignRevision, EngineeringJob | None]:
    revision_number = design.current_revision + 1
    revision = DesignRevision(
        design_id=design.id,
        organization_id=principal.organization_id,
        revision=revision_number,
        status="requirements_review" if missing else "queued",
        change_note=change_note,
        parametric_spec={"schema": "omniweb.parametric-design.v1", "requirements": requirements},
        safety_notice=SAFETY_NOTICE,
        created_by=principal.user_id,
    )
    db.add(revision)
    await db.flush()
    db.add(
        DesignRequirement(
            revision_id=revision.id,
            organization_id=principal.organization_id,
            source_prompt=source_prompt,
            normalized=requirements,
            missing_critical=missing or [],
            assumptions=list(requirements.get("assumptions") or []),
        )
    )
    design.current_revision = revision_number
    design.status = "requirements_review" if missing else "generating"
    job = None
    if not missing:
        job = EngineeringJob(
            design_id=design.id,
            revision_id=revision.id,
            organization_id=principal.organization_id,
            idempotency_key=idempotency_key,
            created_by=principal.user_id,
        )
        db.add(job)
        await db.flush()
    return revision, job


@router.post("/designs", status_code=status.HTTP_202_ACCEPTED)
async def create_design(
    data: DesignCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    existing = await db.scalar(
        select(EngineeringDesign).where(
            EngineeringDesign.organization_id == principal.organization_id,
            EngineeringDesign.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        return await design_view(db, existing, detail=True)
    try:
        extraction = await service.extract(settings, data.prompt)
    except service.EngineeringUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    requirements = extraction.get("requirements") or extraction["extracted"]
    design = EngineeringDesign(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        name=str(requirements.get("component_name") or "Engineering design")[:160],
        component_kind=extraction["component_kind"],
        idempotency_key=data.idempotency_key,
        created_by=principal.user_id,
    )
    db.add(design)
    await db.flush()
    _, job = await create_revision_records(
        db,
        principal,
        design,
        requirements,
        data.prompt,
        "Initial requirements",
        f"{data.idempotency_key}:r1",
        extraction["missing_critical"],
    )
    audit(db, principal, "engineering.design.create", "engineering_design", str(design.id))
    await db.commit()
    if job:
        worker.launch(job.id)
    return await design_view(db, design, detail=True)


@router.get("/designs")
async def list_designs(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(EngineeringDesign)
        .where(
            EngineeringDesign.organization_id == principal.organization_id,
            EngineeringDesign.project_id == project_id,
        )
        .order_by(EngineeringDesign.updated_at.desc())
    )
    return [await design_view(db, row) for row in rows]


@router.get("/designs/{design_id}")
async def get_design(
    design_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    design = await owned_design(db, principal, design_id)
    return await design_view(db, design, detail=True)


@router.post("/designs/{design_id}/revisions", status_code=status.HTTP_202_ACCEPTED)
async def create_revision(
    design_id: uuid.UUID,
    data: RevisionCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    design = await owned_design(db, principal, design_id, write=True)
    if data.requirements.component_kind != design.component_kind:
        raise HTTPException(status_code=422, detail="A revision cannot change component type")
    missing = data.requirements.missing()
    if missing:
        raise HTTPException(status_code=422, detail={"missing_critical": missing})
    active = await db.scalar(
        select(EngineeringJob).where(
            EngineeringJob.design_id == design.id,
            EngineeringJob.status.in_(["queued", "running"]),
        )
    )
    if active:
        raise HTTPException(status_code=409, detail="Wait for the active engineering job")
    existing = await db.scalar(
        select(EngineeringJob).where(
            EngineeringJob.organization_id == principal.organization_id,
            EngineeringJob.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        revision = await db.get(DesignRevision, existing.revision_id)
        return await revision_view(db, revision)
    revision, job = await create_revision_records(
        db,
        principal,
        design,
        data.requirements.model_dump(mode="json"),
        data.source_prompt,
        data.change_note,
        data.idempotency_key,
    )
    audit(db, principal, "engineering.revision.create", "engineering_revision", str(revision.id))
    await db.commit()
    worker.launch(job.id)
    return await revision_view(db, revision)


async def owned_job(
    db: AsyncSession, principal: Principal, job_id: uuid.UUID
) -> tuple[EngineeringJob, EngineeringDesign, DesignRevision]:
    job = await db.scalar(
        select(EngineeringJob).where(
            EngineeringJob.id == job_id,
            EngineeringJob.organization_id == principal.organization_id,
        )
    )
    if not job:
        raise HTTPException(status_code=404, detail="Engineering job not found")
    design = await owned_design(db, principal, job.design_id, write=True)
    revision = await db.get(DesignRevision, job.revision_id)
    return job, design, revision


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    job, design, revision = await owned_job(db, principal, job_id)
    if job.status not in {"failed", "dead_letter"}:
        raise HTTPException(status_code=409, detail="Only failed engineering jobs can be retried")
    if job.attempts >= settings.engineering_max_job_attempts:
        raise HTTPException(
            status_code=409,
            detail="Engineering job reached its retry limit and requires operator review",
        )
    job.status = "queued"
    job.error = None
    job.started_at = None
    job.finished_at = None
    revision.status = "queued"
    design.status = "generating"
    audit(db, principal, "engineering.job.retry", "engineering_job", str(job.id))
    await db.commit()
    worker.launch(job.id)
    return {"id": str(job.id), "status": job.status, "attempts": job.attempts}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    job, design, revision = await owned_job(db, principal, job_id)
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Only active engineering jobs can be cancelled")
    job.status = "cancelled"
    job.error = "Cancelled by user"
    job.finished_at = datetime.now(UTC)
    revision.status = "cancelled"
    design.status = "needs_attention"
    audit(db, principal, "engineering.job.cancel", "engineering_job", str(job.id))
    await db.commit()
    worker.cancel(job.id)
    return {"id": str(job.id), "status": job.status}


@router.post("/designs/{design_id}/approval-request", status_code=status.HTTP_201_CREATED)
async def request_approval(
    design_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    design = await owned_design(db, principal, design_id, write=True)
    revision = await db.scalar(
        select(DesignRevision).where(
            DesignRevision.design_id == design.id,
            DesignRevision.revision == design.current_revision,
        )
    )
    if not revision or revision.status != "validated":
        raise HTTPException(status_code=409, detail="Only geometrically validated revisions can be reviewed")
    approval = Approval(
        project_id=design.project_id,
        organization_id=principal.organization_id,
        kind="engineering_revision",
        summary=f"Review {design.name} revision {revision.revision}"[:300],
        details={"design_id": str(design.id), "revision_id": str(revision.id)},
        requested_by="engineering:design",
    )
    db.add(approval)
    revision.approval_status = "awaiting_review"
    await db.commit()
    return {"approval_id": str(approval.id), "status": approval.status}


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


@router.post("/approvals/{approval_id}")
async def decide_approval(
    approval_id: uuid.UUID,
    data: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    approval = await db.scalar(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.organization_id == principal.organization_id,
            Approval.kind == "engineering_revision",
        )
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Engineering approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval.status}")
    revision = await db.get(DesignRevision, uuid.UUID(approval.details["revision_id"]))
    design = await db.get(EngineeringDesign, uuid.UUID(approval.details["design_id"]))
    approval.status = "approved" if data.decision == "approve" else "rejected"
    approval.decided_by = principal.user_id
    approval.decided_at = datetime.now(UTC)
    revision.approval_status = "engineering_reviewed" if data.decision == "approve" else "rejected"
    design.status = "engineering_reviewed" if data.decision == "approve" else "needs_attention"
    audit(db, principal, f"engineering.approval.{data.decision}", "engineering_revision", str(revision.id))
    await db.commit()
    return {
        "approval_id": str(approval.id),
        "status": approval.status,
        "design_status": design.status,
        "notice": "Review approval does not by itself mean approved for manufacturing.",
    }


class FeedbackInput(BaseModel):
    revision_id: uuid.UUID
    source: str = Field(min_length=3, max_length=160)
    evidence: dict
    authorized: bool


@router.post("/designs/{design_id}/feedback", status_code=status.HTTP_201_CREATED)
async def record_feedback(
    design_id: uuid.UUID,
    data: FeedbackInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    design = await owned_design(db, principal, design_id, write=True)
    revision = await db.get(DesignRevision, data.revision_id)
    if not revision or revision.design_id != design.id:
        raise HTTPException(status_code=404, detail="Engineering revision not found")
    if not data.authorized:
        raise HTTPException(status_code=422, detail="Engineering feedback evidence must be authorized")
    recommendation = {
        "status": "proposal_only",
        "assumptions": ["Manufacturing feedback requires review against the source evidence."],
        "verification_required": [
            "Regenerate geometry",
            "Run Level 1 validation",
            "Obtain explicit design approval",
        ],
    }
    feedback = EngineeringFeedback(
        design_id=design.id,
        revision_id=revision.id,
        organization_id=principal.organization_id,
        source=data.source,
        evidence=data.evidence,
        recommendation=recommendation,
        authorized=True,
        created_by=principal.user_id,
    )
    db.add(feedback)
    await db.flush()
    db.add(
        CapabilityEdge(
            organization_id=principal.organization_id,
            source_type="engineering_feedback",
            source_id=feedback.id,
            relation="proposes_revision_to",
            target_type="engineering_design",
            target_id=design.id,
            metadata_json={"approval_required": True},
        )
    )
    audit(db, principal, "engineering.feedback.create", "engineering_feedback", str(feedback.id))
    await db.commit()
    return {"id": str(feedback.id), "recommendation": recommendation}


async def owned_revision_for_design(
    db: AsyncSession,
    principal: Principal,
    design: EngineeringDesign,
    revision_id: uuid.UUID,
) -> tuple[DesignRevision, DesignRequirement]:
    revision = await db.scalar(
        select(DesignRevision).where(
            DesignRevision.id == revision_id,
            DesignRevision.design_id == design.id,
            DesignRevision.organization_id == principal.organization_id,
        )
    )
    if not revision:
        raise HTTPException(status_code=404, detail="Engineering revision not found")
    requirement = await db.scalar(
        select(DesignRequirement).where(DesignRequirement.revision_id == revision.id)
    )
    if not requirement:
        raise HTTPException(status_code=409, detail="Engineering requirements are unavailable")
    return revision, requirement


class AssemblyMemberInput(BaseModel):
    revision_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=20)
    translation_mm: list[float] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3
    )
    rotation_deg: list[float] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3
    )
    instance_spacing_mm: list[float] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3
    )


class AssemblyCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=2, max_length=160)
    members: list[AssemblyMemberInput] = Field(min_length=2, max_length=50)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")


async def assembly_revision_view(db: AsyncSession, revision: AssemblyRevision) -> dict:
    artifacts = list(
        await db.scalars(
            select(AssemblyArtifact)
            .where(AssemblyArtifact.assembly_revision_id == revision.id)
            .order_by(AssemblyArtifact.format)
        )
    )
    return {
        "id": str(revision.id),
        "revision": revision.revision,
        "status": revision.status,
        "definition": revision.definition,
        "geometry": revision.geometry,
        "preview": revision.preview_mesh,
        "validation_checks": revision.validation_checks,
        "bill_of_materials": revision.bill_of_materials,
        "safety_notice": revision.safety_notice,
        "artifacts": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "format": item.format,
                "filename": item.filename,
                "media_type": item.media_type,
                "sha256": item.sha256,
                "size": item.size,
            }
            for item in artifacts
        ],
        "created_at": revision.created_at.isoformat(),
    }


async def assembly_view(
    db: AsyncSession, assembly: EngineeringAssembly, *, detail: bool = False
) -> dict:
    result = {
        "id": str(assembly.id),
        "project_id": str(assembly.project_id),
        "name": assembly.name,
        "status": assembly.status,
        "current_revision": assembly.current_revision,
        "created_at": assembly.created_at.isoformat(),
        "updated_at": assembly.updated_at.isoformat(),
    }
    if detail:
        revisions = list(
            await db.scalars(
                select(AssemblyRevision)
                .where(AssemblyRevision.assembly_id == assembly.id)
                .order_by(AssemblyRevision.revision.desc())
            )
        )
        result["revisions"] = [
            await assembly_revision_view(db, revision) for revision in revisions
        ]
    return result


async def owned_assembly(
    db: AsyncSession, principal: Principal, assembly_id: uuid.UUID, *, write: bool = False
) -> EngineeringAssembly:
    assembly = await db.scalar(
        select(EngineeringAssembly).where(
            EngineeringAssembly.id == assembly_id,
            EngineeringAssembly.organization_id == principal.organization_id,
        )
    )
    if not assembly:
        raise HTTPException(status_code=404, detail="Engineering assembly not found")
    await project_access(db, assembly.project_id, principal, write=write)
    return assembly


@router.post("/assemblies", status_code=status.HTTP_201_CREATED)
async def create_assembly(
    data: AssemblyCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    if sum(member.quantity for member in data.members) > 50:
        raise HTTPException(status_code=422, detail="An assembly is limited to 50 instances")
    existing = await db.scalar(
        select(EngineeringAssembly).where(
            EngineeringAssembly.organization_id == principal.organization_id,
            EngineeringAssembly.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        return await assembly_view(db, existing, detail=True)

    members = []
    for member in data.members:
        revision = await db.scalar(
            select(DesignRevision).where(
                DesignRevision.id == member.revision_id,
                DesignRevision.organization_id == principal.organization_id,
                DesignRevision.status == "validated",
            )
        )
        if not revision:
            raise HTTPException(
                status_code=422,
                detail="Assemblies require geometrically validated design revisions",
            )
        design = await owned_design(db, principal, revision.design_id)
        if design.project_id != data.project_id:
            raise HTTPException(status_code=422, detail="Assembly members must share a project")
        requirement = await db.scalar(
            select(DesignRequirement).where(DesignRequirement.revision_id == revision.id)
        )
        members.append(
            {
                "member_id": str(revision.id),
                "name": design.name,
                "requirements": requirement.normalized,
                **member.model_dump(mode="json", exclude={"revision_id"}),
            }
        )

    assembly = EngineeringAssembly(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        name=data.name,
        idempotency_key=data.idempotency_key,
        created_by=principal.user_id,
    )
    db.add(assembly)
    await db.flush()
    definition = {"name": data.name, "members": members}
    revision = AssemblyRevision(
        assembly_id=assembly.id,
        organization_id=principal.organization_id,
        revision=1,
        definition=definition,
        created_by=principal.user_id,
    )
    db.add(revision)
    await db.flush()
    try:
        result = await service.generate_assembly(
            settings,
            {
                "assembly_id": str(assembly.id),
                "revision": 1,
                **definition,
            },
        )
    except (service.EngineeringUnavailable, ValueError) as exc:
        await db.rollback()
        status_code = 503 if isinstance(exc, service.EngineeringUnavailable) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    total_bytes = 0
    for payload in result["artifacts"]:
        artifact_data = base64.b64decode(payload["data_base64"], validate=True)
        digest = hashlib.sha256(artifact_data).hexdigest()
        if digest != payload["sha256"] or len(artifact_data) != payload["size"]:
            await db.rollback()
            raise HTTPException(status_code=502, detail="Assembly artifact integrity failed")
        total_bytes += len(artifact_data)
        if total_bytes > settings.engineering_max_artifact_bytes:
            await db.rollback()
            raise HTTPException(status_code=413, detail="Assembly artifact budget exceeded")
        location, stored_digest = AssetStore(settings).put(
            principal.organization_id, artifact_data, payload["format"]
        )
        if stored_digest != digest:
            await db.rollback()
            raise HTTPException(status_code=502, detail="Assembly storage integrity failed")
        db.add(
            AssemblyArtifact(
                assembly_revision_id=revision.id,
                organization_id=principal.organization_id,
                kind=payload["kind"],
                format=payload["format"],
                filename=payload["filename"][:240],
                media_type=payload["media_type"][:100],
                storage_location=location,
                sha256=digest,
                size=len(artifact_data),
            )
        )
    revision.status = result["status"]
    revision.geometry = result["geometry"]
    revision.preview_mesh = result["preview"]
    revision.validation_checks = result["checks"]
    revision.bill_of_materials = result["bill_of_materials"]
    revision.safety_notice = result["safety_notice"]
    assembly.status = result["status"]
    audit(db, principal, "engineering.assembly.create", "engineering_assembly", str(assembly.id))
    await db.commit()
    return await assembly_view(db, assembly, detail=True)


@router.get("/assemblies")
async def list_assemblies(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(EngineeringAssembly)
        .where(
            EngineeringAssembly.project_id == project_id,
            EngineeringAssembly.organization_id == principal.organization_id,
        )
        .order_by(EngineeringAssembly.updated_at.desc())
    )
    return [await assembly_view(db, row) for row in rows]


@router.get("/assemblies/{assembly_id}")
async def get_assembly(
    assembly_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    assembly = await owned_assembly(db, principal, assembly_id)
    return await assembly_view(db, assembly, detail=True)


class ManufacturingEstimateInput(BaseModel):
    revision_id: uuid.UUID
    process: Literal["sheet_metal", "cnc_milling", "laser_cut", "fdm_print"]
    quantity: int = Field(default=1, ge=1, le=100_000)
    material_cost_per_kg: float = Field(gt=0, le=100_000)
    machine_rate_per_hour: float = Field(gt=0, le=100_000)
    labor_rate_per_hour: float = Field(gt=0, le=100_000)
    overhead_percent: float = Field(default=15, ge=0, le=200)


@router.post("/designs/{design_id}/manufacturing-estimates", status_code=201)
async def create_manufacturing_estimate(
    design_id: uuid.UUID,
    data: ManufacturingEstimateInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    design = await owned_design(db, principal, design_id, write=True)
    revision, requirement = await owned_revision_for_design(
        db, principal, design, data.revision_id
    )
    if revision.status != "validated":
        raise HTTPException(status_code=409, detail="Estimate requires validated geometry")
    inputs = data.model_dump(mode="json", exclude={"revision_id"})
    try:
        result = await service.estimate_manufacturing(
            settings,
            {
                "requirements": requirement.normalized,
                "geometry": revision.geometry,
                **inputs,
            },
        )
    except (service.EngineeringUnavailable, ValueError) as exc:
        status_code = 503 if isinstance(exc, service.EngineeringUnavailable) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    estimate = ManufacturingEstimate(
        revision_id=revision.id,
        organization_id=principal.organization_id,
        process=data.process,
        quantity=data.quantity,
        inputs=inputs,
        result=result,
        created_by=principal.user_id,
    )
    db.add(estimate)
    await db.flush()
    audit(
        db,
        principal,
        "engineering.manufacturing.estimate",
        "manufacturing_estimate",
        str(estimate.id),
    )
    await db.commit()
    return {
        "id": str(estimate.id),
        "revision_id": str(revision.id),
        "created_at": estimate.created_at.isoformat(),
        **result,
    }


@router.get("/designs/{design_id}/manufacturing-estimates")
async def list_manufacturing_estimates(
    design_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    design = await owned_design(db, principal, design_id)
    revision_ids = select(DesignRevision.id).where(DesignRevision.design_id == design.id)
    rows = await db.scalars(
        select(ManufacturingEstimate)
        .where(
            ManufacturingEstimate.organization_id == principal.organization_id,
            ManufacturingEstimate.revision_id.in_(revision_ids),
        )
        .order_by(ManufacturingEstimate.created_at.desc())
    )
    return [
        {
            "id": str(row.id),
            "revision_id": str(row.revision_id),
            "created_at": row.created_at.isoformat(),
            **row.result,
        }
        for row in rows
    ]


class SimulationInput(BaseModel):
    revision_id: uuid.UUID
    simulation_type: Literal[
        "static_screening", "thermal_expansion", "modal_screening"
    ]
    load_n: float | None = Field(default=None, gt=0, le=100_000_000)
    span_mm: float | None = Field(default=None, gt=0, le=100_000)
    delta_temperature_c: float | None = Field(default=None, ge=-1_000, le=10_000)
    boundary_condition: Literal["cantilever_fixed"] = "cantilever_fixed"


@router.post("/designs/{design_id}/simulations", status_code=201)
async def create_simulation(
    design_id: uuid.UUID,
    data: SimulationInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    design = await owned_design(db, principal, design_id, write=True)
    revision, requirement = await owned_revision_for_design(
        db, principal, design, data.revision_id
    )
    if revision.status != "validated":
        raise HTTPException(status_code=409, detail="Simulation requires validated geometry")
    inputs = data.model_dump(mode="json", exclude={"revision_id"})
    try:
        result = await service.run_simulation(
            settings,
            {
                "requirements": requirement.normalized,
                "geometry": revision.geometry,
                **inputs,
            },
        )
    except (service.EngineeringUnavailable, ValueError) as exc:
        status_code = 503 if isinstance(exc, service.EngineeringUnavailable) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    simulation = EngineeringSimulation(
        revision_id=revision.id,
        organization_id=principal.organization_id,
        simulation_type=data.simulation_type,
        inputs=inputs,
        result=result,
        created_by=principal.user_id,
    )
    db.add(simulation)
    await db.flush()
    audit(
        db,
        principal,
        "engineering.simulation.create",
        "engineering_simulation",
        str(simulation.id),
    )
    await db.commit()
    return {
        "id": str(simulation.id),
        "revision_id": str(revision.id),
        "created_at": simulation.created_at.isoformat(),
        **result,
    }


@router.get("/designs/{design_id}/simulations")
async def list_simulations(
    design_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    design = await owned_design(db, principal, design_id)
    revision_ids = select(DesignRevision.id).where(DesignRevision.design_id == design.id)
    rows = await db.scalars(
        select(EngineeringSimulation)
        .where(
            EngineeringSimulation.organization_id == principal.organization_id,
            EngineeringSimulation.revision_id.in_(revision_ids),
        )
        .order_by(EngineeringSimulation.created_at.desc())
    )
    return [
        {
            "id": str(row.id),
            "revision_id": str(row.revision_id),
            "created_at": row.created_at.isoformat(),
            **row.result,
        }
        for row in rows
    ]


@router.get("/assembly-artifacts/{artifact_id}")
async def download_assembly_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Response:
    artifact = await db.scalar(
        select(AssemblyArtifact).where(
            AssemblyArtifact.id == artifact_id,
            AssemblyArtifact.organization_id == principal.organization_id,
        )
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Assembly artifact not found")
    revision = await db.get(AssemblyRevision, artifact.assembly_revision_id)
    await owned_assembly(db, principal, revision.assembly_id)
    artifact_data = AssetStore(settings).read(
        principal.organization_id, artifact.storage_location
    )
    if (
        len(artifact_data) != artifact.size
        or hashlib.sha256(artifact_data).hexdigest() != artifact.sha256
    ):
        raise HTTPException(status_code=500, detail="Assembly artifact integrity failed")
    return Response(
        artifact_data,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


async def owned_artifact(
    db: AsyncSession, principal: Principal, artifact_id: uuid.UUID
) -> EngineeringArtifact:
    artifact = await db.scalar(
        select(EngineeringArtifact).where(
            EngineeringArtifact.id == artifact_id,
            EngineeringArtifact.organization_id == principal.organization_id,
        )
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Engineering artifact not found")
    revision = await db.get(DesignRevision, artifact.revision_id)
    await owned_design(db, principal, revision.design_id)
    return artifact


@router.get("/artifacts/{artifact_id}")
async def download_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Response:
    artifact = await owned_artifact(db, principal, artifact_id)
    data = AssetStore(settings).read(principal.organization_id, artifact.storage_location)
    if len(data) != artifact.size or __import__("hashlib").sha256(data).hexdigest() != artifact.sha256:
        raise HTTPException(status_code=500, detail="Engineering artifact integrity check failed")
    return Response(
        data,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


@router.post("/artifacts/{artifact_id}/signed-url")
async def signed_artifact_url(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    await owned_artifact(db, principal, artifact_id)
    expires = int(time.time()) + 600
    token = jwt.encode(
        {
            "sub": str(principal.user_id),
            "org": str(principal.organization_id),
            "artifact": str(artifact_id),
            "exp": expires,
        },
        signing_secret(settings),
        algorithm="HS256",
    )
    return {
        "url": f"/api/v1/engineering/public/artifacts/{artifact_id}?token={token}",
        "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
    }


@router.get("/public/artifacts/{artifact_id}")
async def public_signed_artifact(
    artifact_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        claims = jwt.decode(
            token,
            signing_secret(settings),
            algorithms=["HS256"],
            options={"require": ["exp", "org", "artifact"]},
        )
        if claims["artifact"] != str(artifact_id):
            raise jwt.InvalidTokenError("Artifact scope mismatch")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid artifact link") from exc
    artifact = await db.scalar(
        select(EngineeringArtifact).where(
            EngineeringArtifact.id == artifact_id,
            EngineeringArtifact.organization_id == uuid.UUID(claims["org"]),
        )
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Engineering artifact not found")
    data = AssetStore(settings).read(uuid.UUID(claims["org"]), artifact.storage_location)
    return Response(
        data,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'inline; filename="{artifact.filename}"'},
    )


@router.get("/metrics")
async def engineering_metrics(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    rows = (
        await db.execute(
            select(EngineeringJob.status, func.count(EngineeringJob.id)).where(
                EngineeringJob.organization_id == principal.organization_id
            ).group_by(EngineeringJob.status)
        )
    ).all()
    average = await db.scalar(
        select(func.avg(EngineeringJob.duration_seconds)).where(
            EngineeringJob.organization_id == principal.organization_id,
            EngineeringJob.status == "completed",
        )
    )
    return {
        "jobs": {key: value for key, value in rows},
        "average_duration_seconds": round(float(average), 6) if average is not None else None,
        "compute_cost_usd": 0,
        "note": "Level 1 geometry validation only; structural safety is not evaluated.",
    }
