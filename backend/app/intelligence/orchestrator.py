"""LangGraph supervisor for one unified, potentially multi-intent prompt."""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from ..builder import pipeline
from ..config import get_settings
from ..database import SessionLocal
from ..engineering import service as engineering_service
from ..engineering import worker as engineering_worker
from ..intelligence_models import (
    AssetVersion,
    BusinessPlan,
    BusinessPlanSection,
    ContentAsset,
    DesignRequirement,
    DesignRevision,
    EngineeringDesign,
    EngineeringJob,
    Funnel,
    FunnelVersion,
    IntelligenceTask,
    IntelligenceWorkflow,
    MarketingCampaign,
    MediaJob,
    PlanClaim,
)
from ..models import Membership, Project, User
from ..schemas import Principal
from ..services import aaee
from ..services.media import MediaError, providers
from . import policy

logger = logging.getLogger("omniweb.intelligence")
_running: dict[uuid.UUID, asyncio.Task] = {}

MODES = {
    "AUTO",
    "BUILD",
    "BUSINESS",
    "MARKETING",
    "CONTENT",
    "IMAGE",
    "VIDEO",
    "ENGINEERING",
}
PATTERNS = {
    "build": r"\b(build|website|web app|application|mobile app|software|feature|code)\b",
    "business": r"\b(business plan|business model|market research|pricing strategy|revenue model|go.to.market)\b",
    "marketing": r"\b(marketing|campaign|funnel|audience|seo|keyword|conversion|advertis|lead generation)\b",
    "content": r"\b(blog|article|social (?:media )?posts?|email campaign|copy|product descriptions?|content calendar)\b",
    "image": r"\b(image|images|graphic|banner|illustration|logo|photo|creative)\b",
    "video": r"\b(video|storyboard|video campaign|video brief)\b",
    "engineering": (
        r"\b(cad|engineering drawings?|technical drawings?|parametric|step file|stl|"
        r"bracket|mounting plate|spacer|bushing|shaft|mechanical enclosure)\b"
    ),
}
MODE_KIND = {
    "BUILD": "build",
    "BUSINESS": "business",
    "MARKETING": "marketing",
    "CONTENT": "content",
    "IMAGE": "image",
    "VIDEO": "video",
    "ENGINEERING": "engineering",
}


class GraphState(TypedDict, total=False):
    workflow_id: str
    task_id: str
    done: bool


def detect_intents(prompt: str, mode: str) -> list[str]:
    """Cheap deterministic intent detection. AAEE is not spent classifying ordinary prompts."""
    if mode != "AUTO":
        return [MODE_KIND[mode]]
    low = prompt.lower()
    kinds = [kind for kind, pattern in PATTERNS.items() if re.search(pattern, low)]
    return kinds or ["content"]


def dependency_graph(kinds: list[str]) -> list[dict]:
    """Stable task graph: strategy informs campaigns; campaigns inform creative assets."""
    selected = set(kinds)
    rows = []
    for kind in ("business", "build", "engineering", "marketing", "content", "image", "video"):
        if kind not in selected:
            continue
        dependencies = []
        if kind in {"build", "marketing"} and "business" in selected:
            dependencies.append("business")
        if kind in {"content", "image", "video"} and "marketing" in selected:
            dependencies.append("marketing")
        rows.append(
            {
                "key": kind,
                "kind": kind,
                "title": {
                    "build": "Build the software experience",
                    "business": "Create the business plan",
                    "marketing": "Design the marketing campaign and funnel",
                    "content": "Create campaign content",
                    "image": "Prepare promotional image generation",
                    "video": "Prepare the video campaign",
                    "engineering": "Generate and validate the engineering design",
                }[kind],
                "depends_on": dependencies,
            }
        )
    return rows


async def principal_for(workflow: IntelligenceWorkflow) -> Principal:
    async with SessionLocal() as db:
        user = await db.get(User, workflow.requested_by)
        role = await db.scalar(
            select(Membership.role).where(
                Membership.organization_id == workflow.organization_id,
                Membership.user_id == workflow.requested_by,
            )
        )
    return Principal(
        user_id=workflow.requested_by,
        organization_id=workflow.organization_id,
        email=user.email if user else "workflow@omniweb.local",
        role=role or "member",
        auth_mode="service",
    )


async def supervisor(state: GraphState) -> GraphState:
    async with SessionLocal() as db:
        workflow = await db.get(IntelligenceWorkflow, uuid.UUID(state["workflow_id"]))
        tasks = list(
            await db.scalars(
                select(IntelligenceTask)
                .where(IntelligenceTask.workflow_id == workflow.id)
                .order_by(IntelligenceTask.position)
            )
        )
        completed = {task.key for task in tasks if task.status == "completed"}
        ready = next(
            (
                task
                for task in tasks
                if task.status == "queued" and set(task.depends_on).issubset(completed)
            ),
            None,
        )
        if ready:
            ready.status = "running"
            workflow.status = "running"
            await db.commit()
            return {"task_id": str(ready.id), "done": False}
        failed = any(task.status == "failed" for task in tasks)
        if failed:
            for task in tasks:
                if task.status == "queued":
                    task.status = "failed"
                    task.error = "A dependency failed"
                    task.finished_at = datetime.now(UTC)
        active = any(task.status in {"queued", "running"} for task in tasks)
        workflow.status = "failed" if failed else ("running" if active else "completed")
        if not active:
            workflow.finished_at = datetime.now(UTC)
            workflow.result = {
                "project_id": str(workflow.project_id) if workflow.project_id else None,
                "tasks": {task.key: task.output for task in tasks},
            }
        await db.commit()
        return {"done": not active}


def assessment_for(workflow: IntelligenceWorkflow) -> dict:
    stored = (workflow.context or {}).get("policy_assessment")
    if isinstance(stored, dict) and stored.get("policy_version") == policy.POLICY_VERSION:
        return stored
    return policy.assess(workflow.prompt, detect_intents(workflow.prompt, workflow.mode))


def route(state: GraphState) -> str:
    return END if state.get("done") else "worker"


async def worker(state: GraphState) -> GraphState:
    task_id = uuid.UUID(state["task_id"])
    async with SessionLocal() as db:
        task = await db.get(IntelligenceTask, task_id)
        workflow = await db.get(IntelligenceWorkflow, task.workflow_id)
    try:
        output = await HANDLERS[task.kind](workflow, task)
        assessment = assessment_for(workflow)
        output = {**output, "quality_record": policy.quality_record(task.kind, output, assessment)}
        async with SessionLocal() as db:
            row = await db.get(IntelligenceTask, task_id)
            row.status = "completed"
            row.output = output
            row.finished_at = datetime.now(UTC)
            await db.commit()
    except Exception as exc:
        logger.exception("intelligence task %s failed", task.kind)
        async with SessionLocal() as db:
            row = await db.get(IntelligenceTask, task_id)
            row.status = "failed"
            row.error = str(exc)[:500]
            row.finished_at = datetime.now(UTC)
            await db.commit()
    return {}


async def ask_aaee(
    workflow: IntelligenceWorkflow,
    task: IntelligenceTask,
    task_type: str,
    phase: str,
    system: str,
    fallback: dict,
) -> tuple[dict, dict]:
    settings = get_settings()
    principal = await principal_for(workflow)
    assessment = assessment_for(workflow)
    body = {
        "task_type": task_type,
        "task_description": workflow.prompt,
        "project_id": str(workflow.project_id) if workflow.project_id else None,
        "development_phase": phase,
        "prompt": {
            "system": policy.system_prompt(task.kind, system),
            "user": policy.untrusted(workflow.prompt),
            "response_format": "json",
            "max_output_tokens": policy.TOKEN_BUDGETS.get(task.kind, 2_000),
        },
        "context": {
            "workflow": str(workflow.id),
            "kind": task.kind,
            "policy_version": policy.POLICY_VERSION,
            "risk": assessment["risk"],
        },
        "idempotency_key": f"intel:{workflow.id}:{task.key}",
    }
    try:
        result = await aaee.submit(
            settings,
            principal,
            body,
            project_id=workflow.project_id,
            service="intelligence",
        )
    except (aaee.Unavailable, Exception) as exc:  # AAEE can refuse; deterministic draft is safe.
        logger.info("Using deterministic %s draft: %s", task.kind, exc)
        return fallback, {"strategy": "deterministic", "cost_usd": 0}
    output = (result.get("result") or {}).get("output") or {}
    content = output.get("content")
    try:
        parsed = json.loads(content) if content else None
    except ValueError:
        parsed = None
    return (parsed if isinstance(parsed, dict) else fallback), {
        "aaee_task_id": result["id"],
        "strategy": result.get("strategy"),
        "model": result.get("model"),
        "cost_usd": result.get("total_cost_usd", 0),
    }


async def handle_business(workflow: IntelligenceWorkflow, task: IntelligenceTask) -> dict:
    await ensure_project(workflow)
    sections = [
        ("requirements", "Business requirements"),
        ("market", "Industry and market"),
        ("segments", "Customer segments"),
        ("competition", "Competitive analysis"),
        ("value", "Value proposition"),
        ("model", "Business and revenue model"),
        ("pricing", "Pricing strategy"),
        ("forecasts", "Financial assumptions and scenarios"),
        ("go_to_market", "Go-to-market strategy"),
        ("risks", "Risks"),
        ("roadmap", "Implementation roadmap"),
    ]
    fallback = {
        "title": "Business plan",
        "sections": [
            {
                "key": key,
                "title": title,
                "content": f"Draft {title.lower()} for: {workflow.prompt}",
                "claims": [],
            }
            for key, title in sections
        ],
        "assumptions": [
            "Market size, customer demand, pricing and financial outcomes require sourced research.",
        ],
        "scenarios": [],
    }
    data, usage = await ask_aaee(
        workflow,
        task,
        "requirement_analysis",
        "discovery",
        (
            "You are Omniweb's business planning supervisor. Return JSON with title, sections, "
            "assumptions and scenarios. Each section has key, title, content and claims. Every "
            "claim must have evidence_type source, assumption or projection; sourced claims need "
            "source_url. Never invent market size, customer counts, revenue or financial results."
        ),
        fallback,
    )
    async with SessionLocal() as db:
        plan = BusinessPlan(
            organization_id=workflow.organization_id,
            project_id=workflow.project_id,
            title=str(data.get("title") or "Business plan")[:200],
            assumptions=list(data.get("assumptions") or fallback["assumptions"])[:100],
            scenarios=list(data.get("scenarios") or [])[:12],
            created_by=workflow.requested_by,
        )
        db.add(plan)
        await db.flush()
        for position, source in enumerate((data.get("sections") or fallback["sections"])[:20]):
            section = BusinessPlanSection(
                plan_id=plan.id,
                organization_id=workflow.organization_id,
                key=str(source.get("key") or f"section-{position}")[:64],
                title=str(source.get("title") or "Section")[:160],
                content=str(source.get("content") or ""),
                position=position,
            )
            db.add(section)
            await db.flush()
            for item in (source.get("claims") or [])[:50]:
                kind = item.get("evidence_type")
                url = item.get("source_url")
                if kind not in {"source", "assumption", "projection"} or (
                    kind == "source" and not url
                ):
                    kind, url = "assumption", None
                db.add(
                    PlanClaim(
                        plan_id=plan.id,
                        section_id=section.id,
                        organization_id=workflow.organization_id,
                        claim=str(item.get("claim") or "")[:5_000],
                        evidence_type=kind,
                        source_url=str(url)[:1_000] if url else None,
                        source_title=str(item.get("source_title") or "")[:300] or None,
                    )
                )
        await db.commit()
        return {"plan_id": str(plan.id), **usage}


async def ensure_project(workflow: IntelligenceWorkflow) -> Project:
    async with SessionLocal() as db:
        project = await db.get(Project, workflow.project_id) if workflow.project_id else None
        if not project:
            words = re.findall(r"[A-Za-z0-9]+", workflow.prompt)[:5]
            project = Project(
                organization_id=workflow.organization_id,
                owner_id=workflow.requested_by,
                name=(" ".join(words) or "New project")[:80],
                description=workflow.prompt[:1_000],
                prompt=workflow.prompt,
                template="full-stack",
                stack=["React", "TypeScript", "FastAPI", "PostgreSQL"],
            )
            db.add(project)
            await db.flush()
            workflow.project_id = project.id
            stored = await db.get(IntelligenceWorkflow, workflow.id)
            stored.project_id = project.id
            await db.commit()
        return project


async def handle_build(workflow: IntelligenceWorkflow, task: IntelligenceTask) -> dict:
    project = await ensure_project(workflow)
    principal = await principal_for(workflow)
    async with SessionLocal() as db:
        stored = await db.get(Project, project.id)
        run = await pipeline.create_run(db, stored, principal, "generate")
        await db.commit()
    pipeline.launch(run.id)
    return {"project_id": str(project.id), "builder_run_id": str(run.id), "status": "queued"}


def funnel_definition(prompt: str) -> dict:
    return {
        "type": "lead_generation",
        "steps": [
            {
                "key": "landing",
                "type": "landing_page",
                "title": "A clear path to the outcome",
                "headline": prompt[:180],
                "cta": "Get started",
                "next": "lead-form",
            },
            {
                "key": "lead-form",
                "type": "form",
                "title": "Tell us what you need",
                "fields": ["first_name", "email"],
                "consent_required": True,
                "next": "thank-you",
            },
            {
                "key": "thank-you",
                "type": "thank_you",
                "title": "You're all set",
                "cta": "Return home",
            },
        ],
        "events": ["funnel_entry", "form_submission", "funnel_completion"],
        "mobile_responsive": True,
    }


async def handle_marketing(workflow: IntelligenceWorkflow, task: IntelligenceTask) -> dict:
    project = await ensure_project(workflow)
    fallback = {
        "name": f"{project.name} launch campaign",
        "objective": workflow.prompt,
        "audience": {"status": "assumption", "segments": []},
        "strategy": {"positioning": "Draft pending audience evidence", "channels": []},
        "calendar": [],
        "funnel": funnel_definition(workflow.prompt),
    }
    data, usage = await ask_aaee(
        workflow,
        task,
        "content_generation",
        "discovery",
        (
            "You are Omniweb's digital marketing supervisor. Return JSON with name, objective, "
            "audience, strategy, calendar and funnel. The funnel must include ordered steps. "
            "Never invent performance metrics. Label unsupported audience claims as assumptions."
        ),
        fallback,
    )
    async with SessionLocal() as db:
        campaign = MarketingCampaign(
            organization_id=workflow.organization_id,
            project_id=project.id,
            name=str(data.get("name") or fallback["name"])[:200],
            objective=str(data.get("objective") or workflow.prompt),
            audience=data.get("audience") or {},
            strategy=data.get("strategy") or {},
            calendar=list(data.get("calendar") or [])[:365],
            created_by=workflow.requested_by,
        )
        db.add(campaign)
        await db.flush()
        funnel = Funnel(
            organization_id=workflow.organization_id,
            project_id=project.id,
            campaign_id=campaign.id,
            name=f"{campaign.name} funnel"[:200],
            funnel_type=str((data.get("funnel") or {}).get("type") or "lead_generation")[:32],
            preview_token=uuid.uuid4().hex,
            created_by=workflow.requested_by,
        )
        db.add(funnel)
        await db.flush()
        definition = (
            data.get("funnel") if isinstance(data.get("funnel"), dict) else fallback["funnel"]
        )
        db.add(
            FunnelVersion(
                funnel_id=funnel.id,
                organization_id=workflow.organization_id,
                version=1,
                definition=definition,
                created_by=workflow.requested_by,
            )
        )
        await db.commit()
        return {"campaign_id": str(campaign.id), "funnel_id": str(funnel.id), **usage}


async def handle_content(workflow: IntelligenceWorkflow, task: IntelligenceTask) -> dict:
    fallback = {
        "assets": [
            {"type": "social_post", "title": "Launch post", "content": workflow.prompt},
            {"type": "email", "title": "Launch email", "content": workflow.prompt},
            {"type": "landing_copy", "title": "Landing page copy", "content": workflow.prompt},
        ]
    }
    data, usage = await ask_aaee(
        workflow,
        task,
        "content_generation",
        "implementation",
        (
            "You are Omniweb's content studio. Return JSON assets, each with type, title and "
            "content. Do not state unsupported facts. Mark claims needing evidence with "
            "[EDITORIAL REVIEW]."
        ),
        fallback,
    )
    ids = []
    async with SessionLocal() as db:
        for item in (data.get("assets") or fallback["assets"])[:50]:
            content = str(item.get("content") or "")
            asset = ContentAsset(
                organization_id=workflow.organization_id,
                project_id=workflow.project_id,
                workflow_id=workflow.id,
                content_type=str(item.get("type") or "text")[:40],
                title=str(item.get("title") or "Untitled")[:200],
                prompt_reference=str(workflow.id),
                provider=(usage.get("model") or "").split("/", 1)[0] or None,
                model=usage.get("model"),
                cost_usd=0,
                usage_rights={"status": "review_required"},
                created_by=workflow.requested_by,
            )
            db.add(asset)
            await db.flush()
            db.add(
                AssetVersion(
                    asset_id=asset.id,
                    organization_id=workflow.organization_id,
                    version=1,
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    change_note="Generated from unified create",
                    created_by=workflow.requested_by,
                )
            )
            ids.append(str(asset.id))
        await db.commit()
    return {"asset_ids": ids, **usage}


async def handle_media(workflow: IntelligenceWorkflow, task: IntelligenceTask, kind: str) -> dict:
    settings = get_settings()
    adapter = providers(settings)["openai"]
    capabilities = adapter.capabilities()
    models = capabilities.image_models if kind == "image" else capabilities.video_models
    model = models[0] if models else None
    status, detail, estimate = "capability_unavailable", capabilities.note, 0.0
    if model:
        request = {
            "prompt": workflow.prompt,
            "size": "1024x1024" if kind == "image" else "1280x720",
            "quality": "medium",
            "variants": 1,
            "duration_seconds": 8,
        }
        try:
            estimate = adapter.estimate(kind, model, request)
            status = "awaiting_approval"
            detail = "Approve the estimated cost before provider submission."
        except MediaError as exc:
            status, detail = "capability_unavailable", str(exc)
    else:
        request = {"prompt": workflow.prompt}
    async with SessionLocal() as db:
        job = MediaJob(
            organization_id=workflow.organization_id,
            project_id=workflow.project_id,
            kind=kind,
            provider="openai",
            model=model,
            operation="generate",
            status=status,
            idempotency_key=f"workflow:{workflow.id}:{kind}",
            request=request,
            estimated_cost_usd=estimate,
            error=detail if status == "capability_unavailable" else None,
            created_by=workflow.requested_by,
        )
        db.add(job)
        await db.commit()
        return {"media_job_id": str(job.id), "status": status, "detail": detail}


async def handle_image(workflow: IntelligenceWorkflow, task: IntelligenceTask) -> dict:
    return await handle_media(workflow, task, "image")


async def handle_video(workflow: IntelligenceWorkflow, task: IntelligenceTask) -> dict:
    return await handle_media(workflow, task, "video")


async def handle_engineering(
    workflow: IntelligenceWorkflow, task: IntelligenceTask
) -> dict:
    project = await ensure_project(workflow)
    settings = get_settings()
    extraction = await engineering_service.extract(settings, workflow.prompt)
    requirements = extraction.get("requirements") or extraction["extracted"]
    fallback = {
        "review_notes": [
            "Confirm all critical dimensions and material before manufacturing review.",
            "Level 1 geometry validation does not establish structural safety.",
            *assessment_for(workflow)["professional_review"],
        ]
    }
    review, usage = await ask_aaee(
        workflow,
        task,
        "requirement_analysis",
        "discovery",
        (
            "You are Omniweb's Engineering Supervisor. Review the supplied user request only "
            "for documentation completeness. Return JSON review_notes. Do not invent dimensions, "
            "tolerances, safety factors, loads, standards compliance, or structural conclusions."
        ),
        fallback,
    )
    principal = await principal_for(workflow)
    async with SessionLocal() as db:
        design = EngineeringDesign(
            organization_id=workflow.organization_id,
            project_id=project.id,
            name=str(requirements.get("component_name") or "Engineering design")[:160],
            component_kind=extraction["component_kind"],
            idempotency_key=f"workflow:{workflow.id}",
            status="requirements_review"
            if extraction["missing_critical"]
            else "generating",
            current_revision=1,
            created_by=workflow.requested_by,
        )
        db.add(design)
        await db.flush()
        revision = DesignRevision(
            design_id=design.id,
            organization_id=workflow.organization_id,
            revision=1,
            status="requirements_review"
            if extraction["missing_critical"]
            else "queued",
            change_note="Generated from unified engineering request",
            parametric_spec={
                "schema": "omniweb.parametric-design.v1",
                "requirements": requirements,
                "supervisor_review": review,
            },
            safety_notice=(
                "Geometry validation is not structural analysis, code compliance, engineering "
                "certification, or approval for manufacturing."
            ),
            created_by=workflow.requested_by,
        )
        db.add(revision)
        await db.flush()
        db.add(
            DesignRequirement(
                revision_id=revision.id,
                organization_id=workflow.organization_id,
                source_prompt=workflow.prompt,
                normalized=requirements,
                missing_critical=extraction["missing_critical"],
                assumptions=extraction["assumptions"],
            )
        )
        job = None
        if not extraction["missing_critical"]:
            job = EngineeringJob(
                design_id=design.id,
                revision_id=revision.id,
                organization_id=workflow.organization_id,
                idempotency_key=f"workflow:{workflow.id}:engineering:r1",
                created_by=principal.user_id,
            )
            db.add(job)
            await db.flush()
        await db.commit()
    if job:
        engineering_worker.launch(job.id)
    return {
        "design_id": str(design.id),
        "revision_id": str(revision.id),
        "job_id": str(job.id) if job else None,
        "status": "queued" if job else "requirements_review",
        "missing_critical": extraction["missing_critical"],
        "questions": extraction["questions"],
        **usage,
    }


HANDLERS = {
    "business": handle_business,
    "build": handle_build,
    "marketing": handle_marketing,
    "content": handle_content,
    "image": handle_image,
    "video": handle_video,
    "engineering": handle_engineering,
}


def graph():
    builder = StateGraph(GraphState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("worker", worker)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route, {"worker": "worker", END: END})
    builder.add_edge("worker", "supervisor")
    return builder.compile()


async def execute(workflow_id: uuid.UUID) -> None:
    try:
        await graph().ainvoke({"workflow_id": str(workflow_id)})
    finally:
        _running.pop(workflow_id, None)


def launch(workflow_id: uuid.UUID) -> None:
    running = _running.get(workflow_id)
    if not running or running.done():
        _running[workflow_id] = asyncio.create_task(execute(workflow_id))


async def resume_all() -> None:
    async with SessionLocal() as db:
        ids = list(
            await db.scalars(
                select(IntelligenceWorkflow.id).where(
                    IntelligenceWorkflow.status.in_(["queued", "running"])
                )
            )
        )
        for task in await db.scalars(
            select(IntelligenceTask).where(IntelligenceTask.status == "running")
        ):
            task.status = "queued"
        await db.commit()
    for workflow_id in ids:
        launch(workflow_id)


async def stop_all() -> None:
    running = list(_running.values())
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
    _running.clear()
