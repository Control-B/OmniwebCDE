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
    CapabilityEdge,
    DesignRequirement,
    DesignRevision,
    EngineeringArtifact,
    EngineeringDesign,
    EngineeringFeedback,
    EngineeringJob,
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
