"""Campaigns, funnels, CMS, CRM, first-party analytics and durable automations."""

import hashlib
import html
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .intelligence_models import (
    ArticleVersion,
    AutomationRun,
    AutomationWorkflow,
    BlogArticle,
    BlogSite,
    BrandKit,
    ContentAsset,
    CrmContact,
    ExperimentVariant,
    Funnel,
    FunnelVersion,
    MarketingCampaign,
    MarketingEvent,
    MarketingExperiment,
)
from .models import Approval
from .projects_api import audit, project_access
from .schemas import Principal
from .security import get_principal, require_admin

router = APIRouter(prefix="/api/v1")
FUNNEL_TYPES = {
    "lead_generation",
    "appointment_booking",
    "product_sales",
    "webinar_registration",
    "free_trial",
    "email_list",
    "consultation",
    "digital_product",
    "onboarding",
}
EVENTS = {
    "page_view",
    "funnel_entry",
    "form_submission",
    "cta_interaction",
    "funnel_completion",
    "appointment_conversion",
    "checkout_completion",
    "content_engagement",
}


async def campaign_owned(
    db: AsyncSession, principal: Principal, campaign_id: uuid.UUID
) -> MarketingCampaign:
    row = await db.scalar(
        select(MarketingCampaign).where(
            MarketingCampaign.id == campaign_id,
            MarketingCampaign.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await project_access(db, row.project_id, principal)
    return row


def campaign_view(row: MarketingCampaign) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "brand_kit_id": str(row.brand_kit_id) if row.brand_kit_id else None,
        "name": row.name,
        "objective": row.objective,
        "status": row.status,
        "audience": row.audience,
        "strategy": row.strategy,
        "calendar": row.calendar,
        "budget_limit_usd": row.budget_limit_usd,
        "spend_usd": row.spend_usd,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


# Brand kits ------------------------------------------------------------------------------------


def brand_kit_view(row: BrandKit) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id) if row.project_id else None,
        "name": row.name,
        "logo_asset_id": str(row.logo_asset_id) if row.logo_asset_id else None,
        "colors": row.colors,
        "typography": row.typography,
        "voice": row.voice,
        "messaging": row.messaging,
        "updated_at": row.updated_at.isoformat(),
    }


class BrandKitInput(BaseModel):
    project_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=160)
    logo_asset_id: uuid.UUID | None = None
    colors: list[str] = Field(default_factory=list, max_length=20)
    typography: dict = Field(default_factory=dict)
    voice: str = Field(default="", max_length=20_000)
    messaging: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("colors")
    @classmethod
    def valid_colors(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in value):
            raise ValueError("Colors must be six-digit hexadecimal values")
        return value


async def validate_brand_assets(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID | None, logo_asset_id: uuid.UUID | None
) -> None:
    if project_id:
        await project_access(db, project_id, principal, write=True)
    if logo_asset_id:
        asset = await db.scalar(
            select(ContentAsset).where(
                ContentAsset.id == logo_asset_id,
                ContentAsset.organization_id == principal.organization_id,
            )
        )
        if not asset or (project_id and asset.project_id not in {None, project_id}):
            raise HTTPException(status_code=422, detail="Logo asset is outside this project")


@router.get("/brand-kits")
async def brand_kits(
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    query = select(BrandKit).where(BrandKit.organization_id == principal.organization_id)
    if project_id:
        await project_access(db, project_id, principal)
        query = query.where(BrandKit.project_id == project_id)
    elif principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Choose a project")
    rows = await db.scalars(query.order_by(BrandKit.updated_at.desc()))
    return [brand_kit_view(row) for row in rows]


@router.post("/brand-kits", status_code=status.HTTP_201_CREATED)
async def create_brand_kit(
    data: BrandKitInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    await validate_brand_assets(db, principal, data.project_id, data.logo_asset_id)
    row = BrandKit(organization_id=principal.organization_id, **data.model_dump())
    db.add(row)
    await db.flush()
    audit(db, principal, "brand_kit.create", "brand_kit", str(row.id))
    await db.commit()
    return brand_kit_view(row)


@router.put("/brand-kits/{brand_kit_id}")
async def update_brand_kit(
    brand_kit_id: uuid.UUID,
    data: BrandKitInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await db.scalar(
        select(BrandKit).where(
            BrandKit.id == brand_kit_id,
            BrandKit.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Brand kit not found")
    await validate_brand_assets(db, principal, data.project_id, data.logo_asset_id)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, principal, "brand_kit.update", "brand_kit", str(row.id))
    await db.commit()
    return brand_kit_view(row)


@router.get("/campaigns")
async def campaigns(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(MarketingCampaign)
        .where(
            MarketingCampaign.organization_id == principal.organization_id,
            MarketingCampaign.project_id == project_id,
        )
        .order_by(MarketingCampaign.updated_at.desc())
    )
    return [campaign_view(row) for row in rows]


class CampaignInput(BaseModel):
    project_id: uuid.UUID
    brand_kit_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=200)
    objective: str = Field(min_length=3, max_length=10_000)
    audience: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)
    calendar: list = Field(default_factory=list, max_length=365)
    budget_limit_usd: float = Field(default=0, ge=0, le=10_000_000)


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    data: CampaignInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    if data.brand_kit_id:
        kit = await db.scalar(
            select(BrandKit).where(
                BrandKit.id == data.brand_kit_id,
                BrandKit.organization_id == principal.organization_id,
            )
        )
        if not kit or kit.project_id not in {None, data.project_id}:
            raise HTTPException(status_code=422, detail="Brand kit is outside this project")
    row = MarketingCampaign(
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        **data.model_dump(),
    )
    db.add(row)
    await db.commit()
    return campaign_view(row)


class CampaignEdit(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    objective: str | None = Field(default=None, min_length=3, max_length=10_000)
    audience: dict | None = None
    strategy: dict | None = None
    calendar: list | None = Field(default=None, max_length=365)
    budget_limit_usd: float | None = Field(default=None, ge=0, le=10_000_000)


@router.patch("/campaigns/{campaign_id}")
async def edit_campaign(
    campaign_id: uuid.UUID,
    data: CampaignEdit,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await campaign_owned(db, principal, campaign_id)
    await project_access(db, row.project_id, principal, write=True)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    await db.commit()
    return campaign_view(row)


@router.post("/campaigns/{campaign_id}/publish-request", status_code=status.HTTP_201_CREATED)
async def request_campaign_publish(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await campaign_owned(db, principal, campaign_id)
    await project_access(db, row.project_id, principal, write=True)
    approval = Approval(
        project_id=row.project_id,
        organization_id=principal.organization_id,
        kind="campaign_publish",
        summary=f"Activate campaign: {row.name}"[:300],
        details={"campaign_id": str(row.id)},
        requested_by="marketing:campaign",
    )
    db.add(approval)
    row.status = "awaiting_approval"
    await db.commit()
    return {"campaign": campaign_view(row), "approval_id": str(approval.id)}


# Funnels ---------------------------------------------------------------------------------------


async def funnel_owned(
    db: AsyncSession, principal: Principal, funnel_id: uuid.UUID, write: bool = False
) -> Funnel:
    row = await db.scalar(
        select(Funnel).where(
            Funnel.id == funnel_id,
            Funnel.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Funnel not found")
    await project_access(db, row.project_id, principal, write=write)
    return row


async def funnel_definition(db: AsyncSession, funnel: Funnel) -> dict:
    version = await db.scalar(
        select(FunnelVersion).where(
            FunnelVersion.funnel_id == funnel.id,
            FunnelVersion.version == funnel.current_version,
        )
    )
    return version.definition if version else {}


async def funnel_view(db: AsyncSession, row: Funnel) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "campaign_id": str(row.campaign_id) if row.campaign_id else None,
        "name": row.name,
        "funnel_type": row.funnel_type,
        "status": row.status,
        "current_version": row.current_version,
        "preview_url": f"/funnel-preview/{row.preview_token}" if row.preview_token else None,
        "custom_domain": row.custom_domain,
        "domain_verified": row.domain_verified,
        "definition": await funnel_definition(db, row),
    }


@router.get("/funnels")
async def funnels(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(Funnel)
        .where(Funnel.organization_id == principal.organization_id, Funnel.project_id == project_id)
        .order_by(Funnel.updated_at.desc())
    )
    return [await funnel_view(db, row) for row in rows]


class FunnelInput(BaseModel):
    project_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=200)
    funnel_type: str
    definition: dict

    @field_validator("funnel_type")
    @classmethod
    def type_supported(cls, value: str) -> str:
        if value not in FUNNEL_TYPES:
            raise ValueError("Unsupported funnel type")
        return value


def validate_funnel(definition: dict) -> None:
    steps = definition.get("steps")
    if not isinstance(steps, list) or len(steps) < 2 or len(steps) > 30:
        raise HTTPException(status_code=422, detail="A funnel needs 2–30 ordered steps")
    keys = {str(step.get("key")) for step in steps if isinstance(step, dict)}
    if len(keys) != len(steps) or "None" in keys:
        raise HTTPException(status_code=422, detail="Every funnel step needs a unique key")
    allowed = {"landing_page", "form", "thank_you", "booking", "checkout", "content", "condition"}
    if any(step.get("type") not in allowed for step in steps):
        raise HTTPException(status_code=422, detail="Unsupported funnel step")
    for step in steps:
        if step.get("next") and step["next"] not in keys:
            raise HTTPException(
                status_code=422, detail=f"Step {step['key']} points to an unknown next step"
            )


@router.post("/funnels", status_code=status.HTTP_201_CREATED)
async def create_funnel(
    data: FunnelInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    if data.campaign_id:
        campaign = await campaign_owned(db, principal, data.campaign_id)
        if campaign.project_id != data.project_id:
            raise HTTPException(status_code=422, detail="Campaign and funnel must share a project")
    validate_funnel(data.definition)
    row = Funnel(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        campaign_id=data.campaign_id,
        name=data.name,
        funnel_type=data.funnel_type,
        preview_token=uuid.uuid4().hex,
        created_by=principal.user_id,
    )
    db.add(row)
    await db.flush()
    db.add(
        FunnelVersion(
            funnel_id=row.id,
            organization_id=principal.organization_id,
            version=1,
            definition=data.definition,
            created_by=principal.user_id,
        )
    )
    await db.commit()
    return await funnel_view(db, row)


class FunnelEdit(BaseModel):
    definition: dict
    change_note: str = Field(default="Edited", max_length=300)


@router.post("/funnels/{funnel_id}/versions", status_code=status.HTTP_201_CREATED)
async def edit_funnel(
    funnel_id: uuid.UUID,
    data: FunnelEdit,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await funnel_owned(db, principal, funnel_id, write=True)
    validate_funnel(data.definition)
    row.current_version += 1
    row.status = "draft"
    db.add(
        FunnelVersion(
            funnel_id=row.id,
            organization_id=principal.organization_id,
            version=row.current_version,
            definition={**data.definition, "change_note": data.change_note},
            created_by=principal.user_id,
        )
    )
    await db.commit()
    return await funnel_view(db, row)


@router.post("/funnels/{funnel_id}/rollback/{version}")
async def rollback_funnel(
    funnel_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await funnel_owned(db, principal, funnel_id, write=True)
    source = await db.scalar(
        select(FunnelVersion).where(
            FunnelVersion.funnel_id == row.id, FunnelVersion.version == version
        )
    )
    if not source:
        raise HTTPException(status_code=404, detail="Funnel version not found")
    row.current_version += 1
    row.status = "draft"
    db.add(
        FunnelVersion(
            funnel_id=row.id,
            organization_id=principal.organization_id,
            version=row.current_version,
            definition={**source.definition, "restored_from": version},
            created_by=principal.user_id,
        )
    )
    await db.commit()
    return await funnel_view(db, row)


@router.get("/funnels/{funnel_id}/preview")
async def preview_funnel(
    funnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await funnel_owned(db, principal, funnel_id)
    return await funnel_view(db, row)


@router.get("/funnel-preview/{token}")
async def public_funnel_preview(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(Funnel).where(Funnel.preview_token == token))
    if not row:
        raise HTTPException(status_code=404, detail="Preview not found")
    return {
        "name": row.name,
        "status": "preview",
        "definition": await funnel_definition(db, row),
        "robots": "noindex,nofollow",
    }


@router.post("/funnels/{funnel_id}/publish-request", status_code=status.HTTP_201_CREATED)
async def request_funnel_publish(
    funnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await funnel_owned(db, principal, funnel_id, write=True)
    if row.custom_domain and not row.domain_verified:
        raise HTTPException(
            status_code=409, detail="Verify custom-domain ownership before publishing"
        )
    approval = Approval(
        project_id=row.project_id,
        organization_id=principal.organization_id,
        kind="funnel_publish",
        summary=f"Publish funnel: {row.name}"[:300],
        details={"funnel_id": str(row.id), "version": row.current_version},
        requested_by="marketing:funnel",
    )
    db.add(approval)
    row.status = "awaiting_approval"
    await db.commit()
    return {"funnel": await funnel_view(db, row), "approval_id": str(approval.id)}


# Publication approvals -------------------------------------------------------------------------


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]


@router.post("/marketing/approvals/{approval_id}")
async def marketing_approval(
    approval_id: uuid.UUID,
    data: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    approval = await db.scalar(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.organization_id == principal.organization_id,
        )
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval.status}")
    approval.status = "approved" if data.decision == "approve" else "rejected"
    approval.decided_by = principal.user_id
    approval.decided_at = datetime.now(UTC)
    target = None
    if approval.kind == "funnel_publish":
        target = await db.get(Funnel, uuid.UUID(approval.details["funnel_id"]))
        target.status = "published" if data.decision == "approve" else "draft"
        if data.decision == "approve":
            version = await db.scalar(
                select(FunnelVersion).where(
                    FunnelVersion.funnel_id == target.id,
                    FunnelVersion.version == target.current_version,
                )
            )
            version.status = "published"
    elif approval.kind == "blog_publish":
        target = await db.get(BlogArticle, uuid.UUID(approval.details["article_id"]))
        target.status = "published" if data.decision == "approve" else "draft"
        target.published_at = datetime.now(UTC) if data.decision == "approve" else None
    elif approval.kind == "campaign_publish":
        target = await db.get(MarketingCampaign, uuid.UUID(approval.details["campaign_id"]))
        target.status = "active" if data.decision == "approve" else "draft"
    else:
        raise HTTPException(status_code=422, detail="This approval is not a marketing publication")
    audit(db, principal, f"marketing.approval.{data.decision}", approval.kind, str(approval.id))
    await db.commit()
    return {"approval_id": str(approval.id), "status": approval.status}


# CRM lead capture and first-party events -------------------------------------------------------


class LeadInput(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=160)
    consent: bool
    consent_text: str = Field(default="", max_length=500)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")
    honeypot: str = Field(default="", max_length=100)
    fields: dict = Field(default_factory=dict)
    utm: dict = Field(default_factory=dict)


@router.post("/public/funnels/{funnel_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_funnel(
    funnel_id: uuid.UUID,
    data: LeadInput,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if data.honeypot:
        return {"accepted": True}
    funnel = await db.get(Funnel, funnel_id)
    if not funnel or funnel.status != "published":
        raise HTTPException(status_code=404, detail="Published funnel not found")
    existing_event = await db.scalar(
        select(MarketingEvent).where(
            MarketingEvent.organization_id == funnel.organization_id,
            MarketingEvent.idempotency_key == data.idempotency_key,
        )
    )
    if existing_event:
        return {"accepted": True, "contact_id": str(existing_event.contact_id)}
    email = str(data.email).strip().lower()
    contact = await db.scalar(
        select(CrmContact).where(
            CrmContact.organization_id == funnel.organization_id,
            CrmContact.email_normalized == email,
        )
    )
    if not contact:
        contact = CrmContact(
            organization_id=funnel.organization_id,
            project_id=funnel.project_id,
            email=str(data.email),
            email_normalized=email,
            source=f"funnel:{funnel.id}",
        )
        db.add(contact)
        await db.flush()
    contact.first_name = data.first_name or contact.first_name
    contact.last_name = data.last_name or contact.last_name
    contact.company = data.company or contact.company
    contact.custom_fields = {**contact.custom_fields, **data.fields}
    if data.consent:
        contact.marketing_consent = True
        contact.consent_source = data.consent_text or f"funnel:{funnel.id}"
        contact.consent_at = datetime.now(UTC)
    event = MarketingEvent(
        organization_id=funnel.organization_id,
        project_id=funnel.project_id,
        campaign_id=funnel.campaign_id,
        funnel_id=funnel.id,
        contact_id=contact.id,
        event_type="form_submission",
        idempotency_key=data.idempotency_key,
        properties={"fields": sorted(data.fields)},
        attribution=data.utm,
        consent={"marketing": data.consent, "text": data.consent_text[:500]},
    )
    db.add(event)
    await db.commit()
    await trigger_automations(
        db, funnel.organization_id, "form_submitted", contact, {"funnel_id": str(funnel.id)}
    )
    return {"accepted": True, "contact_id": str(contact.id)}


class EventInput(BaseModel):
    event_type: str
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,100}$")
    project_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    funnel_id: uuid.UUID | None = None
    session_id: str | None = Field(default=None, max_length=100)
    properties: dict = Field(default_factory=dict)
    attribution: dict = Field(default_factory=dict)
    consent: dict

    @field_validator("event_type")
    @classmethod
    def supported_event(cls, value: str) -> str:
        if value not in EVENTS:
            raise ValueError("Unsupported marketing event")
        return value


@router.post("/marketing/events", status_code=status.HTTP_202_ACCEPTED)
async def capture_event(
    data: EventInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    if not data.consent.get("analytics"):
        raise HTTPException(status_code=422, detail="Analytics consent is required")
    if data.project_id:
        await project_access(db, data.project_id, principal)
    existing = await db.scalar(
        select(MarketingEvent).where(
            MarketingEvent.organization_id == principal.organization_id,
            MarketingEvent.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        return {"id": str(existing.id), "recorded": False}
    row = MarketingEvent(
        organization_id=principal.organization_id,
        **data.model_dump(),
    )
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "recorded": True}


@router.get("/marketing/analytics")
async def marketing_analytics(
    project_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    await project_access(db, project_id, principal)
    query = select(MarketingEvent.event_type, func.count(MarketingEvent.id)).where(
        MarketingEvent.organization_id == principal.organization_id,
        MarketingEvent.project_id == project_id,
    )
    if campaign_id:
        query = query.where(MarketingEvent.campaign_id == campaign_id)
    rows = (await db.execute(query.group_by(MarketingEvent.event_type))).all()
    counts = {kind: count for kind, count in rows}
    entries = counts.get("funnel_entry", 0)
    completions = counts.get("funnel_completion", 0)
    forms = counts.get("form_submission", 0)
    campaign = await db.get(MarketingCampaign, campaign_id) if campaign_id else None
    return {
        "events": counts,
        "visitors": counts.get("page_view", 0),
        "leads": forms,
        "funnel_conversion_rate": round(completions / entries, 4) if entries else None,
        "campaign_cost_usd": campaign.spend_usd if campaign else None,
        "cost_per_lead_usd": round(campaign.spend_usd / forms, 4) if campaign and forms else None,
        "note": "Only recorded first-party events are shown. Missing metrics are null, never estimated.",
    }


# A/B experiments ------------------------------------------------------------------------------


class VariantInput(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=120)
    weight: int = Field(ge=1, le=99)
    definition: dict = Field(default_factory=dict)


class ExperimentInput(BaseModel):
    project_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=200)
    hypothesis: str = Field(min_length=3, max_length=10_000)
    metric: str
    minimum_sample_size: int = Field(default=30, ge=20, le=1_000_000)
    variants: list[VariantInput] = Field(min_length=2, max_length=10)

    @field_validator("metric")
    @classmethod
    def metric_supported(cls, value: str) -> str:
        if value not in EVENTS:
            raise ValueError("Metric must be a supported marketing event")
        return value

    @field_validator("variants")
    @classmethod
    def variants_valid(cls, value: list[VariantInput]) -> list[VariantInput]:
        if len({item.key for item in value}) != len(value):
            raise ValueError("Variant keys must be unique")
        if sum(item.weight for item in value) != 100:
            raise ValueError("Variant weights must total 100")
        return value


async def experiment_owned(
    db: AsyncSession, principal: Principal, experiment_id: uuid.UUID, write: bool = False
) -> MarketingExperiment:
    row = await db.scalar(
        select(MarketingExperiment).where(
            MarketingExperiment.id == experiment_id,
            MarketingExperiment.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await project_access(db, row.project_id, principal, write=write)
    return row


async def experiment_view(db: AsyncSession, row: MarketingExperiment) -> dict:
    variants = await db.scalars(
        select(ExperimentVariant)
        .where(ExperimentVariant.experiment_id == row.id)
        .order_by(ExperimentVariant.key)
    )
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "campaign_id": str(row.campaign_id) if row.campaign_id else None,
        "name": row.name,
        "hypothesis": row.hypothesis,
        "metric": row.metric,
        "status": row.status,
        "minimum_sample_size": row.minimum_sample_size,
        "result": row.result,
        "variants": [
            {
                "id": str(item.id),
                "key": item.key,
                "name": item.name,
                "weight": item.weight,
                "definition": item.definition,
            }
            for item in variants
        ],
    }


@router.post("/marketing/experiments", status_code=status.HTTP_201_CREATED)
async def create_experiment(
    data: ExperimentInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    await project_access(db, data.project_id, principal, write=True)
    if data.campaign_id:
        campaign = await campaign_owned(db, principal, data.campaign_id)
        if campaign.project_id != data.project_id:
            raise HTTPException(status_code=422, detail="Campaign and experiment must share a project")
    row = MarketingExperiment(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        campaign_id=data.campaign_id,
        name=data.name,
        hypothesis=data.hypothesis,
        metric=data.metric,
        minimum_sample_size=data.minimum_sample_size,
        created_by=principal.user_id,
    )
    db.add(row)
    await db.flush()
    for variant in data.variants:
        db.add(
            ExperimentVariant(
                experiment_id=row.id,
                organization_id=principal.organization_id,
                **variant.model_dump(),
            )
        )
    audit(db, principal, "marketing.experiment.create", "marketing_experiment", str(row.id))
    await db.commit()
    return await experiment_view(db, row)


@router.post("/marketing/experiments/{experiment_id}/activate")
async def activate_experiment(
    experiment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    row = await experiment_owned(db, principal, experiment_id, write=True)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail=f"Experiment is {row.status}")
    row.status = "active"
    audit(db, principal, "marketing.experiment.activate", "marketing_experiment", str(row.id))
    await db.commit()
    return await experiment_view(db, row)


@router.get("/marketing/experiments/{experiment_id}/assignment")
async def assign_experiment(
    experiment_id: uuid.UUID,
    subject_id: str = Query(min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await experiment_owned(db, principal, experiment_id)
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Experiment is not active")
    variants = list(
        await db.scalars(
            select(ExperimentVariant)
            .where(ExperimentVariant.experiment_id == row.id)
            .order_by(ExperimentVariant.key)
        )
    )
    bucket = int(hashlib.sha256(f"{row.id}:{subject_id}".encode()).hexdigest()[:8], 16) % 100
    cursor = 0
    selected = variants[-1]
    for variant in variants:
        cursor += variant.weight
        if bucket < cursor:
            selected = variant
            break
    return {
        "experiment_id": str(row.id),
        "variant_key": selected.key,
        "definition": selected.definition,
        "tracking_properties": {
            "experiment_id": str(row.id),
            "variant_key": selected.key,
            "assignment_bucket": bucket,
        },
    }


@router.post("/marketing/experiments/{experiment_id}/evaluate")
async def evaluate_experiment(
    experiment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    row = await experiment_owned(db, principal, experiment_id, write=True)
    variants = list(
        await db.scalars(select(ExperimentVariant).where(ExperimentVariant.experiment_id == row.id))
    )
    events = list(
        await db.scalars(
            select(MarketingEvent).where(
                MarketingEvent.organization_id == principal.organization_id,
                MarketingEvent.project_id == row.project_id,
            )
        )
    )
    counts = {variant.key: {"exposures": 0, "conversions": 0} for variant in variants}
    for event in events:
        if event.properties.get("experiment_id") != str(row.id):
            continue
        key = event.properties.get("variant_key")
        if key not in counts:
            continue
        if event.event_type == "page_view":
            counts[key]["exposures"] += 1
        if event.event_type == row.metric:
            counts[key]["conversions"] += 1
    sample_size = sum(item["exposures"] for item in counts.values())
    rates = {
        key: (round(item["conversions"] / item["exposures"], 6) if item["exposures"] else None)
        for key, item in counts.items()
    }
    conclusive = sample_size >= row.minimum_sample_size and all(rate is not None for rate in rates.values())
    winner = max(rates, key=lambda key: rates[key] or 0) if conclusive else None
    row.result = {
        "sample_size": sample_size,
        "counts": counts,
        "rates": rates,
        "winner": winner,
        "conclusion": "observed_leader" if conclusive else "inconclusive",
        "note": "An observed leader is not proof of causation or statistical significance.",
    }
    row.status = "evaluated" if conclusive else "inconclusive"
    audit(db, principal, "marketing.experiment.evaluate", "marketing_experiment", str(row.id))
    await db.commit()
    return await experiment_view(db, row)


@router.get("/crm/contacts")
async def contacts(
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    query = (
        select(CrmContact)
        .where(CrmContact.organization_id == principal.organization_id)
        .order_by(CrmContact.updated_at.desc())
        .limit(500)
    )
    if project_id:
        await project_access(db, project_id, principal)
        query = query.where(CrmContact.project_id == project_id)
    elif principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Choose a project")
    return [
        {
            "id": str(row.id),
            "project_id": str(row.project_id) if row.project_id else None,
            "email": row.email,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "company": row.company,
            "source": row.source,
            "stage": row.stage,
            "score": row.score,
            "tags": row.tags,
            "marketing_consent": row.marketing_consent,
            "unsubscribed": row.unsubscribed_at is not None,
        }
        for row in await db.scalars(query)
    ]


@router.get("/crm/contacts/export.csv")
async def export_contacts(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> Response:
    rows = await db.scalars(
        select(CrmContact)
        .where(CrmContact.organization_id == principal.organization_id)
        .order_by(CrmContact.created_at)
    )
    lines = ["email,first_name,last_name,company,stage,marketing_consent"]
    for row in rows:
        values = [
            row.email,
            row.first_name,
            row.last_name,
            row.company,
            row.stage,
            str(row.marketing_consent).lower(),
        ]
        lines.append(",".join('"' + value.replace('"', '""') + '"' for value in values))
    return Response(
        "\n".join(lines),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contacts.csv"'},
    )


@router.post("/public/unsubscribe/{contact_id}")
async def unsubscribe(contact_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(CrmContact, contact_id)
    if row:
        row.unsubscribed_at = datetime.now(UTC)
        row.marketing_consent = False
        await db.commit()
    return {"unsubscribed": True}


# Blog CMS --------------------------------------------------------------------------------------


def slugify(value: str) -> str:
    return (
        re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")[:200] or "article"
    )


@router.post("/blogs", status_code=status.HTTP_201_CREATED)
async def create_blog(
    data: dict,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    project_id = uuid.UUID(data["project_id"])
    await project_access(db, project_id, principal, write=True)
    name = str(data.get("name") or "Blog")[:160]
    row = BlogSite(
        organization_id=principal.organization_id,
        project_id=project_id,
        name=name,
        slug=slugify(str(data.get("slug") or name))[:100],
        settings=data.get("settings") or {},
    )
    db.add(row)
    await db.commit()
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "slug": row.slug,
    }


class ArticleInput(BaseModel):
    title: str = Field(min_length=2, max_length=250)
    content: str = Field(max_length=2_000_000)
    slug: str | None = Field(default=None, max_length=200)
    seo_title: str | None = Field(default=None, max_length=70)
    meta_description: str | None = Field(default=None, max_length=170)
    canonical_url: str | None = Field(default=None, max_length=1000)
    categories: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=50)
    claims: list[dict] = Field(default_factory=list, max_length=100)


@router.post("/blogs/{blog_id}/articles", status_code=status.HTTP_201_CREATED)
async def create_article(
    blog_id: uuid.UUID,
    data: ArticleInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    blog = await db.scalar(
        select(BlogSite).where(
            BlogSite.id == blog_id,
            BlogSite.organization_id == principal.organization_id,
        )
    )
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    await project_access(db, blog.project_id, principal, write=True)
    for claim in data.claims:
        kind = claim.get("evidence_type")
        if kind == "source" and not claim.get("source_url"):
            raise HTTPException(status_code=422, detail="Sourced claims need a source URL")
        if kind not in {"source", "assumption", "projection"}:
            raise HTTPException(
                status_code=422,
                detail="Every factual claim must be sourced or marked as an assumption/projection",
            )
    slug = slugify(data.slug or data.title)
    article = BlogArticle(
        blog_id=blog.id,
        organization_id=principal.organization_id,
        title=data.title,
        slug=slug,
        seo={
            "title": data.seo_title or data.title[:70],
            "description": data.meta_description or "",
            "canonical_url": data.canonical_url,
            "schema_org": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": data.title,
            },
        },
        categories=data.categories,
        tags=data.tags,
        created_by=principal.user_id,
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleVersion(
            article_id=article.id,
            organization_id=principal.organization_id,
            version=1,
            content=data.content,
            claims=data.claims,
            created_by=principal.user_id,
        )
    )
    await db.commit()
    return {
        "id": str(article.id),
        "slug": article.slug,
        "status": article.status,
        "version": 1,
        "seo": article.seo,
    }


@router.post("/articles/{article_id}/publish-request", status_code=status.HTTP_201_CREATED)
async def request_article_publish(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    article = await db.scalar(
        select(BlogArticle).where(
            BlogArticle.id == article_id,
            BlogArticle.organization_id == principal.organization_id,
        )
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    blog = await db.get(BlogSite, article.blog_id)
    await project_access(db, blog.project_id, principal, write=True)
    version = await db.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version == article.current_version,
        )
    )
    unsupported = [
        c for c in version.claims if c.get("evidence_type") == "source" and not c.get("source_url")
    ]
    if unsupported:
        raise HTTPException(
            status_code=409, detail="Resolve unsupported factual claims before publication"
        )
    approval = Approval(
        project_id=blog.project_id,
        organization_id=principal.organization_id,
        kind="blog_publish",
        summary=f"Publish article: {article.title}"[:300],
        details={"article_id": str(article.id), "version": article.current_version},
        requested_by="marketing:cms",
    )
    db.add(approval)
    article.status = "awaiting_approval"
    await db.commit()
    return {
        "article_id": str(article.id),
        "approval_id": str(approval.id),
        "status": article.status,
    }


@router.get("/public/blogs/{blog_id}/articles/{slug}")
async def public_article(blog_id: uuid.UUID, slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    article = await db.scalar(
        select(BlogArticle).where(
            BlogArticle.blog_id == blog_id,
            BlogArticle.slug == slug,
            BlogArticle.status == "published",
        )
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    version = await db.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version == article.current_version,
        )
    )
    return {
        "title": article.title,
        "slug": article.slug,
        "content": version.content,
        "seo": article.seo,
        "categories": article.categories,
        "tags": article.tags,
        "published_at": article.published_at.isoformat(),
    }


@router.get("/public/blogs/{blog_id}/sitemap.xml")
async def sitemap(blog_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Response:
    blog = await db.get(BlogSite, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    articles = await db.scalars(
        select(BlogArticle).where(BlogArticle.blog_id == blog.id, BlogArticle.status == "published")
    )
    base = (
        f"https://{blog.custom_domain}"
        if blog.custom_domain and blog.domain_verified
        else f"/public/blogs/{blog.id}"
    )
    urls = "".join(
        f"<url><loc>{html.escape(base + '/' + article.slug)}</loc></url>" for article in articles
    )
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        media_type="application/xml",
    )


@router.get("/public/blogs/{blog_id}/rss.xml")
async def rss(blog_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Response:
    blog = await db.get(BlogSite, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    articles = await db.scalars(
        select(BlogArticle)
        .where(BlogArticle.blog_id == blog.id, BlogArticle.status == "published")
        .order_by(BlogArticle.published_at.desc())
        .limit(50)
    )
    items = "".join(
        f"<item><title>{html.escape(article.title)}</title><guid>{article.id}</guid></item>"
        for article in articles
    )
    return Response(
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>{html.escape(blog.name)}</title>{items}</channel></rss>',
        media_type="application/rss+xml",
    )


# Durable marketing automation ------------------------------------------------------------------


TRIGGERS = {
    "form_submitted",
    "lead_created",
    "funnel_step_completed",
    "appointment_booked",
    "email_engagement",
    "segment_entered",
    "scheduled",
    "webhook",
    "software_capability_released",
}
ACTIONS = {
    "send_email",
    "wait",
    "branch",
    "update_contact",
    "assign_lead",
    "create_task",
    "webhook",
    "request_ai_content",
    "notify_user",
    "add_tag",
    "follow_up",
}


class AutomationInput(BaseModel):
    project_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=200)
    trigger: dict
    steps: list[dict] = Field(min_length=1, max_length=50)

    @field_validator("trigger")
    @classmethod
    def trigger_supported(cls, value: dict) -> dict:
        if value.get("type") not in TRIGGERS:
            raise ValueError("Unsupported automation trigger")
        return value

    @field_validator("steps")
    @classmethod
    def steps_supported(cls, value: list[dict]) -> list[dict]:
        if any(step.get("action") not in ACTIONS for step in value):
            raise ValueError("Unsupported automation action")
        return value


@router.post("/automations", status_code=status.HTTP_201_CREATED)
async def create_automation(
    data: AutomationInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    if data.project_id:
        await project_access(db, data.project_id, principal, write=True)
    row = AutomationWorkflow(
        organization_id=principal.organization_id,
        project_id=data.project_id,
        name=data.name,
        trigger=data.trigger,
        steps=data.steps,
        created_by=principal.user_id,
    )
    db.add(row)
    await db.commit()
    return {
        "id": str(row.id),
        "name": row.name,
        "status": row.status,
        "trigger": row.trigger,
        "steps": row.steps,
    }


@router.post("/automations/{workflow_id}/activate")
async def activate_automation(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> dict:
    row = await db.scalar(
        select(AutomationWorkflow).where(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.organization_id == principal.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Automation not found")
    # External side effects need an authorized provider and per-action policy. Activation alone
    # never sends email, posts a webhook or spends money.
    row.status = "active"
    audit(db, principal, "automation.activate", "automation", str(row.id))
    await db.commit()
    return {"id": str(row.id), "status": row.status}


async def trigger_automations(
    db: AsyncSession,
    organization_id: uuid.UUID,
    trigger: str,
    contact: CrmContact,
    context: dict,
) -> None:
    workflows = list(
        await db.scalars(
            select(AutomationWorkflow).where(
                AutomationWorkflow.organization_id == organization_id,
                AutomationWorkflow.status == "active",
            )
        )
    )
    for workflow in workflows:
        if workflow.trigger.get("type") != trigger:
            continue
        key = hashlib.sha256(f"{workflow.id}:{contact.id}:{context}".encode()).hexdigest()
        existing = await db.scalar(
            select(AutomationRun).where(
                AutomationRun.workflow_id == workflow.id,
                AutomationRun.idempotency_key == key,
            )
        )
        if existing:
            continue
        run = AutomationRun(
            workflow_id=workflow.id,
            organization_id=organization_id,
            idempotency_key=key,
            status="running",
            context={"contact_id": str(contact.id), **context},
        )
        db.add(run)
        await db.flush()
        logs = []
        for position, step in enumerate(workflow.steps):
            action = step["action"]
            result = "completed"
            detail = ""
            if action == "send_email":
                if not contact.marketing_consent or contact.unsubscribed_at:
                    result, detail = "blocked", "Consent or suppression prevents marketing email"
                else:
                    # No delivery provider is configured in this slice. Never claim delivery.
                    result, detail = (
                        "provider_unavailable",
                        "No authorized email delivery provider is configured",
                    )
            elif action == "add_tag":
                contact.tags = sorted({*contact.tags, str(step.get("tag") or "")} - {""})
            elif action == "update_contact":
                if step.get("stage"):
                    contact.stage = str(step["stage"])[:40]
            elif action in {"webhook", "request_ai_content", "follow_up"}:
                result, detail = (
                    "approval_required",
                    "External or generative action requires an authorized execution",
                )
            logs.append(
                {
                    "position": position,
                    "action": action,
                    "status": result,
                    "detail": detail,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
        run.logs = logs
        run.cursor = len(workflow.steps)
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
    await db.commit()


@router.get("/automations/{workflow_id}/runs")
async def automation_runs(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    workflow = await db.scalar(
        select(AutomationWorkflow).where(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.organization_id == principal.organization_id,
        )
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Automation not found")
    rows = await db.scalars(
        select(AutomationRun)
        .where(AutomationRun.workflow_id == workflow.id)
        .order_by(AutomationRun.created_at.desc())
    )
    return [
        {
            "id": str(row.id),
            "status": row.status,
            "cursor": row.cursor,
            "context": row.context,
            "logs": row.logs,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
