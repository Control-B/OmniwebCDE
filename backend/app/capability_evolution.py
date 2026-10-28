"""Evidence-driven bidirectional software/marketing capability evolution service."""

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .builder import pipeline
from .database import get_db
from .intelligence_models import (
    AssetVersion,
    Capability,
    CapabilityEdge,
    ContentAsset,
    EvolutionCase,
    EvolutionEvidence,
    EvolutionTransition,
)
from .models import GenerationRun, Project
from .projects_api import audit, project_access
from .schemas import Principal
from .security import get_principal, require_admin

router = APIRouter(prefix="/api/v1/evolution")

STATES = {
    "OBSERVED",
    "EVIDENCE_COLLECTED",
    "HYPOTHESIS_CREATED",
    "CAPABILITY_MATCHED",
    "CHANGE_PROPOSED",
    "APPROVED",
    "IMPLEMENTED",
    "VERIFIED",
    "RELEASED",
    "OUTCOME_MEASURED",
    "REJECTED",
    "FAILED",
    "ROLLED_BACK",
    "INCONCLUSIVE",
}
NEXT = {
    "OBSERVED": {"EVIDENCE_COLLECTED", "REJECTED", "FAILED"},
    "EVIDENCE_COLLECTED": {"HYPOTHESIS_CREATED", "REJECTED", "FAILED"},
    "HYPOTHESIS_CREATED": {"CAPABILITY_MATCHED", "REJECTED", "FAILED"},
    "CAPABILITY_MATCHED": {"CHANGE_PROPOSED", "REJECTED", "FAILED"},
    "CHANGE_PROPOSED": {"APPROVED", "REJECTED"},
    "APPROVED": {"IMPLEMENTED", "FAILED"},
    "IMPLEMENTED": {"VERIFIED", "FAILED", "ROLLED_BACK"},
    "VERIFIED": {"RELEASED", "FAILED", "ROLLED_BACK"},
    "RELEASED": {"OUTCOME_MEASURED", "INCONCLUSIVE", "ROLLED_BACK"},
    "OUTCOME_MEASURED": set(),
    "REJECTED": set(),
    "FAILED": set(),
    "ROLLED_BACK": set(),
    "INCONCLUSIVE": set(),
}
CATALOG = [
    ("authentication", "Authentication", ["sign in", "login", "account", "authentication"]),
    (
        "appointment-scheduling",
        "Appointment scheduling",
        ["booking", "appointment", "calendar", "schedule"],
    ),
    ("shopping-cart", "Shopping cart", ["cart", "checkout", "product sales"]),
    ("payments", "Payments", ["payment", "billing", "checkout", "invoice"]),
    ("customer-messaging", "Customer messaging", ["chat", "message", "notification"]),
    ("lead-capture", "Lead capture", ["lead", "form", "quote request"]),
    ("crm", "CRM integration", ["crm", "contact", "pipeline"]),
    ("analytics", "Analytics", ["analytics", "tracking", "conversion", "abandon"]),
    ("customer-onboarding", "Customer onboarding", ["onboarding", "activation", "signup"]),
]


async def ensure_catalog(db: AsyncSession) -> None:
    if await db.scalar(
        select(func.count(Capability.id)).where(Capability.organization_id.is_(None))
    ):
        return
    for key, name, tags in CATALOG:
        db.add(
            Capability(
                key=key,
                name=name,
                description=f"Reusable, tested {name.lower()} capability.",
                tags=tags,
                requirements=[],
                test_evidence=[],
            )
        )
    await db.commit()


async def owned_case(
    db: AsyncSession, principal: Principal, case_id: uuid.UUID, write: bool = False
) -> EvolutionCase:
    row = await db.scalar(
        select(EvolutionCase).where(
            EvolutionCase.id == case_id,
            EvolutionCase.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Improvement case not found")
    await project_access(db, row.project_id, principal, write=write)
    return row


async def transition(
    db: AsyncSession,
    row: EvolutionCase,
    to_state: str,
    principal: Principal,
    reason: str,
    evidence_ids: list[str] | None = None,
    *,
    bootstrap: bool = False,
) -> None:
    if to_state not in STATES:
        raise HTTPException(status_code=422, detail="Unknown lifecycle state")
    if not bootstrap and to_state not in NEXT.get(row.state, set()):
        raise HTTPException(status_code=409, detail=f"Cannot transition {row.state} to {to_state}")
    version = (
        await db.scalar(
            select(func.max(EvolutionTransition.version)).where(
                EvolutionTransition.case_id == row.id
            )
        )
        or 0
    ) + 1
    old = row.state
    row.state = to_state
    row.updated_at = datetime.now(UTC)
    db.add(
        EvolutionTransition(
            case_id=row.id,
            organization_id=row.organization_id,
            version=version,
            from_state=old if version > 1 else None,
            to_state=to_state,
            reason=reason[:500],
            evidence_ids=evidence_ids or [],
            actor_id=principal.user_id,
        )
    )


def link(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    relation: str,
    target_type: str,
    target_id: uuid.UUID,
    metadata: dict | None = None,
) -> None:
    db.add(
        CapabilityEdge(
            organization_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            relation=relation,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
        )
    )


def case_view(row: EvolutionCase) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "campaign_id": str(row.campaign_id) if row.campaign_id else None,
        "direction": row.direction,
        "state": row.state,
        "title": row.title,
        "objective": row.objective,
        "hypothesis": row.hypothesis,
        "alternatives": row.alternatives,
        "selected_capability_id": str(row.selected_capability_id)
        if row.selected_capability_id
        else None,
        "implementation_run_id": str(row.implementation_run_id)
        if row.implementation_run_id
        else None,
        "outcome": row.outcome,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


class EvidenceInput(BaseModel):
    evidence_type: Literal["analytics", "experiment", "release", "test", "research"]
    source: str = Field(min_length=3, max_length=300)
    payload: dict
    authorized: bool


class ObservationInput(BaseModel):
    project_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=3, max_length=10_000)
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=50)


@router.post("/observations", status_code=status.HTTP_201_CREATED)
async def observe(
    data: ObservationInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    if not all(item.authorized for item in data.evidence):
        raise HTTPException(status_code=422, detail="All observation evidence must be authorized")
    row = EvolutionCase(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        campaign_id=data.campaign_id,
        direction="marketing_to_software",
        title=data.title,
        objective=data.objective,
        created_by=principal.user_id,
    )
    db.add(row)
    await db.flush()
    await transition(
        db, row, "OBSERVED", principal, "Authorized observation recorded", bootstrap=True
    )
    ids = []
    for item in data.evidence:
        evidence = EvolutionEvidence(
            case_id=row.id,
            organization_id=principal.organization_id,
            **item.model_dump(),
        )
        db.add(evidence)
        await db.flush()
        ids.append(str(evidence.id))
        link(
            db,
            principal.organization_id,
            "evolution_case",
            row.id,
            "supported_by",
            "evidence",
            evidence.id,
        )
    await transition(
        db,
        row,
        "EVIDENCE_COLLECTED",
        principal,
        "Authorized evidence attached",
        ids,
    )
    audit(db, principal, "evolution.observation.create", "evolution_case", str(row.id))
    await db.commit()
    return case_view(row)


@router.post("/cases/{case_id}/analyze")
async def analyze(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await owned_case(db, principal, case_id, write=True)
    if row.state != "EVIDENCE_COLLECTED":
        raise HTTPException(status_code=409, detail="The case is not ready for analysis")
    await ensure_catalog(db)
    text = f"{row.title} {row.objective}".lower()
    catalog = list(
        await db.scalars(
            select(Capability).where(
                or_(
                    Capability.organization_id.is_(None),
                    Capability.organization_id == principal.organization_id,
                )
            )
        )
    )
    scored = []
    words = set(re.findall(r"[a-z0-9]+", text))
    for capability in catalog:
        score = sum(1 for tag in capability.tags if set(tag.split()) & words)
        if score:
            scored.append((score, capability))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    best = scored[0][1] if scored else None
    row.hypothesis = {
        "statement": f"The observed outcome may be affected by: {row.objective}",
        "causation_status": "hypothesis_not_proven",
        "recommended_validation": "Use a controlled comparison where feasible.",
    }
    await transition(db, row, "HYPOTHESIS_CREATED", principal, "Structured hypothesis created")
    alternatives = []
    if best:
        alternatives.extend(
            [
                {
                    "path": "reuse",
                    "capability_id": str(best.id),
                    "name": best.name,
                    "engineering_cost": "low",
                    "risk": "lower",
                    "tradeoff": "Fastest; constrained to catalog behavior.",
                },
                {
                    "path": "adapt",
                    "capability_id": str(best.id),
                    "name": best.name,
                    "engineering_cost": "medium",
                    "risk": "medium",
                    "tradeoff": "More tailored; requires regression testing.",
                },
            ]
        )
        row.selected_capability_id = best.id
        link(
            db,
            principal.organization_id,
            "evolution_case",
            row.id,
            "matched_to",
            "capability",
            best.id,
            {"match_basis": "catalog_tags"},
        )
    alternatives.append(
        {
            "path": "synthesize",
            "name": "New capability",
            "engineering_cost": "unknown_pending_architecture",
            "risk": "higher",
            "tradeoff": "Custom fit; requires architecture, implementation, security validation and approval.",
        }
    )
    row.alternatives = alternatives
    await transition(db, row, "CAPABILITY_MATCHED", principal, "Catalog alternatives evaluated")
    await transition(
        db, row, "CHANGE_PROPOSED", principal, "Reuse, adapt and synthesis tradeoffs proposed"
    )
    await db.commit()
    return case_view(row)


class SelectionInput(BaseModel):
    decision: Literal["approve", "reject"]
    path: Literal["reuse", "adapt", "synthesize"] | None = None
    capability_id: uuid.UUID | None = None


@router.post("/cases/{case_id}/decision")
async def decide(
    case_id: uuid.UUID,
    data: SelectionInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    row = await owned_case(db, principal, case_id, write=True)
    if row.state != "CHANGE_PROPOSED":
        raise HTTPException(status_code=409, detail="The case is not waiting for a decision")
    if data.decision == "reject":
        await transition(db, row, "REJECTED", principal, "Proposal rejected")
    else:
        if not data.path:
            raise HTTPException(status_code=422, detail="Choose reuse, adapt or synthesize")
        valid = any(
            alternative["path"] == data.path
            and (
                data.path == "synthesize"
                or not data.capability_id
                or alternative.get("capability_id") == str(data.capability_id)
            )
            for alternative in row.alternatives
        )
        if not valid:
            raise HTTPException(status_code=422, detail="Selected alternative is not available")
        if data.capability_id:
            row.selected_capability_id = data.capability_id
        row.hypothesis = {**row.hypothesis, "selected_path": data.path}
        await transition(db, row, "APPROVED", principal, f"Approved {data.path} alternative")
    audit(db, principal, f"evolution.proposal.{data.decision}", "evolution_case", str(row.id))
    await db.commit()
    return case_view(row)


@router.post("/cases/{case_id}/implement", status_code=status.HTTP_202_ACCEPTED)
async def implement(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    row = await owned_case(db, principal, case_id, write=True)
    if row.state != "APPROVED":
        raise HTTPException(status_code=409, detail="Approve the capability change first")
    project = await db.get(Project, row.project_id)
    path = row.hypothesis.get("selected_path")
    capability = (
        await db.get(Capability, row.selected_capability_id) if row.selected_capability_id else None
    )
    instruction = (
        f"{'Integrate' if path == 'reuse' else 'Adapt'} the tested {capability.name} capability to address: {row.objective}"
        if capability and path != "synthesize"
        else f"Design and implement a new capability to address: {row.objective}"
    )
    run = await pipeline.create_run(
        db, project, principal, "edit" if project.spec else "generate", instruction=instruction
    )
    await db.commit()
    row = await owned_case(db, principal, case_id, write=True)
    row.implementation_run_id = run.id
    await db.commit()
    pipeline.launch(run.id)
    return {**case_view(row), "implementation_status": run.status}


class VerificationInput(BaseModel):
    tests_passed: bool
    security_passed: bool
    preview_url: str | None = Field(default=None, max_length=1000)
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=50)


@router.post("/cases/{case_id}/verify")
async def verify(
    case_id: uuid.UUID,
    data: VerificationInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await owned_case(db, principal, case_id, write=True)
    if row.state != "APPROVED" or not row.implementation_run_id:
        raise HTTPException(
            status_code=409, detail="No approved implementation is pending verification"
        )
    run = await db.get(GenerationRun, row.implementation_run_id)
    if run.status != "succeeded" or not data.tests_passed or not data.security_passed:
        raise HTTPException(
            status_code=409, detail="The implementation and required checks must pass"
        )
    ids = []
    for item in data.evidence:
        if not item.authorized:
            raise HTTPException(status_code=422, detail="Verification evidence must be authorized")
        evidence = EvolutionEvidence(
            case_id=row.id,
            organization_id=row.organization_id,
            **item.model_dump(),
        )
        db.add(evidence)
        await db.flush()
        ids.append(str(evidence.id))
    await transition(db, row, "IMPLEMENTED", principal, "Builder implementation completed")
    await transition(db, row, "VERIFIED", principal, "Tests and security checks passed", ids)
    row.outcome = {**row.outcome, "preview_url": data.preview_url}
    await db.commit()
    return case_view(row)


@router.post("/cases/{case_id}/release")
async def release(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    row = await owned_case(db, principal, case_id, write=True)
    if row.state != "VERIFIED":
        raise HTTPException(status_code=409, detail="Only a verified capability can be released")
    await transition(db, row, "RELEASED", principal, "Release approved")
    capability = (
        await db.get(Capability, row.selected_capability_id) if row.selected_capability_id else None
    )
    if capability:
        capability.status = "released"
        capability.release_metadata = {
            "released_at": datetime.now(UTC).isoformat(),
            "project_id": str(row.project_id),
            "case_id": str(row.id),
        }
    await make_marketing_proposals(db, row, principal, capability.name if capability else row.title)
    audit(db, principal, "evolution.release", "evolution_case", str(row.id))
    await db.commit()
    return case_view(row)


async def make_marketing_proposals(
    db: AsyncSession,
    row: EvolutionCase,
    principal: Principal,
    feature: str,
) -> list[str]:
    ids = []
    proposals = [
        (
            "landing_copy",
            f"Messaging update for {feature}",
            f"Draft messaging for the verified release: {feature}. Publication approval is required.",
        ),
        (
            "social_post",
            f"Release announcement for {feature}",
            f"Draft announcement for {feature}. Confirm audience availability before publication.",
        ),
        (
            "video_brief",
            f"Video brief for {feature}",
            f"Show how the verified {feature} helps its intended audience. Do not claim unsupported outcomes.",
        ),
    ]
    for content_type, title, content in proposals:
        asset = ContentAsset(
            organization_id=row.organization_id,
            project_id=row.project_id,
            campaign_id=row.campaign_id,
            content_type=content_type,
            title=title[:200],
            status="draft",
            usage_rights={"status": "review_required"},
            metadata_json={
                "evolution_case_id": str(row.id),
                "verified_release": True,
                "publication_requires_approval": True,
            },
            created_by=principal.user_id,
        )
        db.add(asset)
        await db.flush()
        link(
            db,
            row.organization_id,
            "evolution_case",
            row.id,
            "proposes",
            "content_asset",
            asset.id,
            {"verified_release": True},
        )
        db.add(
            AssetVersion(
                asset_id=asset.id,
                organization_id=row.organization_id,
                version=1,
                content=content,
                content_hash=__import__("hashlib").sha256(content.encode()).hexdigest(),
                change_note="Proposed from verified software release",
                created_by=principal.user_id,
            )
        )
        ids.append(str(asset.id))
    row.outcome = {**row.outcome, "marketing_proposal_asset_ids": ids}
    return ids


class OutcomeInput(BaseModel):
    metric: str = Field(min_length=2, max_length=100)
    baseline: float
    observed: float
    higher_is_better: bool = True
    sample_size: int = Field(ge=0)
    evidence: EvidenceInput


@router.post("/cases/{case_id}/outcome")
async def outcome(
    case_id: uuid.UUID,
    data: OutcomeInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await owned_case(db, principal, case_id, write=True)
    if row.state != "RELEASED":
        raise HTTPException(status_code=409, detail="Outcomes can only be measured after release")
    if not data.evidence.authorized:
        raise HTTPException(status_code=422, detail="Outcome evidence must be authorized")
    evidence = EvolutionEvidence(
        case_id=row.id,
        organization_id=row.organization_id,
        **data.evidence.model_dump(),
    )
    db.add(evidence)
    await db.flush()
    delta = data.observed - data.baseline
    improved = delta > 0 if data.higher_is_better else delta < 0
    conclusive = data.sample_size >= 30 and data.baseline != data.observed
    row.outcome = {
        **row.outcome,
        "metric": data.metric,
        "baseline": data.baseline,
        "observed": data.observed,
        "delta": delta,
        "sample_size": data.sample_size,
        "improved": improved if conclusive else None,
        "causation_status": "not_proven_without_controlled_comparison",
    }
    state = "OUTCOME_MEASURED" if conclusive else "INCONCLUSIVE"
    await transition(
        db, row, state, principal, "Measured authorized post-release outcome", [str(evidence.id)]
    )
    await db.commit()
    return case_view(row)


class ReleaseInput(BaseModel):
    project_id: uuid.UUID
    capability_name: str = Field(min_length=2, max_length=160)
    release_version: str = Field(min_length=1, max_length=40)
    released: bool
    audience: list[str] = Field(default_factory=list, max_length=50)
    test_evidence: list[dict] = Field(min_length=1, max_length=50)


@router.post("/releases", status_code=status.HTTP_201_CREATED)
async def software_release_to_marketing(
    data: ReleaseInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    if not data.released or not all(item.get("passed") for item in data.test_evidence):
        raise HTTPException(
            status_code=409,
            detail="Unreleased or unverified features cannot generate live marketing claims",
        )
    capability = Capability(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        key=re.sub(r"[^a-z0-9]+", "-", data.capability_name.lower()).strip("-")[:100],
        name=data.capability_name,
        version=data.release_version,
        status="released",
        description=f"Verified release of {data.capability_name}",
        test_evidence=data.test_evidence,
        release_metadata={
            "released_at": datetime.now(UTC).isoformat(),
            "audience": data.audience,
        },
    )
    db.add(capability)
    await db.flush()
    row = EvolutionCase(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        direction="software_to_marketing",
        title=f"Market verified release: {data.capability_name}",
        objective="Update messaging and campaigns for the verified software release.",
        state="VERIFIED",
        selected_capability_id=capability.id,
        hypothesis={
            "verified_release": True,
            "audience": data.audience,
            "advertising_status": "proposal_only",
        },
        created_by=principal.user_id,
    )
    db.add(row)
    await db.flush()
    await transition(
        db, row, "VERIFIED", principal, "Verified software release received", bootstrap=True
    )
    await transition(db, row, "RELEASED", principal, "Release metadata confirms availability")
    assets = await make_marketing_proposals(db, row, principal, capability.name)
    await db.commit()
    return {**case_view(row), "marketing_proposal_asset_ids": assets}


@router.get("/cases")
async def cases(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(EvolutionCase)
        .where(
            EvolutionCase.organization_id == principal.organization_id,
            EvolutionCase.project_id == project_id,
        )
        .order_by(EvolutionCase.updated_at.desc())
    )
    return [case_view(row) for row in rows]


@router.get("/cases/{case_id}")
async def get_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await owned_case(db, principal, case_id)
    evidence = await db.scalars(
        select(EvolutionEvidence).where(EvolutionEvidence.case_id == row.id)
    )
    transitions = await db.scalars(
        select(EvolutionTransition)
        .where(EvolutionTransition.case_id == row.id)
        .order_by(EvolutionTransition.version)
    )
    return {
        **case_view(row),
        "evidence": [
            {
                "id": str(item.id),
                "type": item.evidence_type,
                "source": item.source,
                "payload": item.payload,
                "authorized": item.authorized,
            }
            for item in evidence
        ],
        "transitions": [
            {
                "version": item.version,
                "from": item.from_state,
                "to": item.to_state,
                "reason": item.reason,
                "evidence_ids": item.evidence_ids,
                "at": item.created_at.isoformat(),
            }
            for item in transitions
        ],
    }


@router.get("/graph")
async def graph(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    rows = await db.scalars(
        select(CapabilityEdge)
        .where(CapabilityEdge.organization_id == principal.organization_id)
        .order_by(CapabilityEdge.created_at.desc())
        .limit(500)
    )
    return [
        {
            "source": {"type": row.source_type, "id": str(row.source_id)},
            "relation": row.relation,
            "target": {"type": row.target_type, "id": str(row.target_id)},
            "metadata": row.metadata_json,
        }
        for row in rows
    ]
