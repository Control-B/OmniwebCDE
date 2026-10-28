import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .builder import pipeline, preview
from .builder.store import ProjectStore
from .config import Settings, get_settings
from .database import get_db
from .models import (
    AgentExecution,
    Approval,
    AuditEvent,
    Checkpoint,
    Conversation,
    Deployment,
    GenerationRun,
    Membership,
    Message,
    Project,
    ProjectEnvVar,
    ProjectMember,
    User,
)
from .schemas import Principal
from .security import encrypt_secret, get_principal, require_admin
from .services import gateway

router = APIRouter(prefix="/api/v1")

TEMPLATES = {
    "react-web": {"label": "Web application", "stack": ["React", "TypeScript", "Vite", "Tailwind CSS", "Vitest"]},
    "fastapi-backend": {"label": "Backend API", "stack": ["FastAPI", "PostgreSQL", "SQLAlchemy", "Alembic", "OpenAPI", "pytest"]},
    "expo-mobile": {"label": "Mobile application", "stack": ["React Native", "Expo", "TypeScript"]},
    "full-stack": {"label": "Full-stack application", "stack": ["React", "Vite", "FastAPI", "PostgreSQL", "Alembic", "Typed API client"]},
}
REQUIREMENTS_SYSTEM_PROMPT = (
    "You are Omniweb's requirements assistant. Help the user define the application they want to build. "
    "Restate the goal in one sentence, list the main user roles, list user stories as 'As a <role>, I want ...', "
    "and ask at most three clarifying questions that would change the architecture. Be concise. "
    "You do not write code yourself: when the user is ready, they press Generate and Omniweb's build pipeline creates, "
    "tests, and previews the app. Never claim that code was generated, built, tested, or deployed."
)
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
WRITE_ROLES = {"owner", "editor"}


class ProjectCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=8000)
    name: str | None = Field(default=None, min_length=2, max_length=80)
    template: Literal["react-web", "fastapi-backend", "expo-mobile", "full-stack"] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=8000)
    template: Literal["react-web", "fastapi-backend", "expo-mobile", "full-stack"] | None = None
    app_config: dict | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    tier: Literal["economy", "standard", "advanced", "self_hosted"] | None = None
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


class MemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["editor", "viewer"] = "editor"


class EnvVarInput(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: SecretStr
    environment: Literal["development", "production"] = "development"


class CredentialInput(BaseModel):
    api_key: SecretStr | None = None
    base_url: str = Field(default="", max_length=300)


class BudgetInput(BaseModel):
    limit_usd: float = Field(ge=0, le=100_000)
    hard_limit: bool = True
    alert_threshold: float = Field(default=0.8, gt=0, le=1)


class PreferenceInput(BaseModel):
    default_tier: Literal["economy", "standard", "advanced", "self_hosted"] = "standard"
    allowed_providers: list[str] = Field(default_factory=list)
    pinned_models: dict[str, str] = Field(default_factory=dict)
    max_escalations: int | None = Field(default=None, ge=0, le=2)


def derive_name(prompt: str) -> str:
    quoted = re.search(r"[\"“']([^\"”']{2,60})[\"”']", prompt)
    if quoted:
        return quoted.group(1).strip()
    called = re.search(r"\b(?:called|named)\s+([A-Z][\w&' -]{1,40})", prompt)
    if called:
        return called.group(1).strip()
    subject = re.sub(r"^(build|create|make|generate)\s+(me\s+)?(an?|the)\s+", "", prompt.strip(), flags=re.IGNORECASE)
    words = re.split(r"\s+(?:with|that|for|which|where)\s+", subject, maxsplit=1)[0].split()[:5]
    name = " ".join(words).strip(" .,") or "Untitled project"
    return name[:1].upper() + name[1:80]


def infer_template(prompt: str) -> str:
    text = prompt.lower()
    mobile = bool(re.search(r"\b(mobile|ios|android|expo|react native)\b", text))
    backend = bool(re.search(r"\b(database|backend|api|login|auth|accounts?|payments?|users?|roles?|dashboard)\b", text))
    if mobile or backend:
        return "full-stack"
    return "react-web"


async def project_access(db: AsyncSession, project_id: uuid.UUID, principal: Principal, write: bool = False) -> tuple[Project, str]:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.organization_id == principal.organization_id)
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if principal.role in {"owner", "admin"}:
        role = "owner"
    else:
        role = await db.scalar(
            select(ProjectMember.role).where(ProjectMember.project_id == project.id, ProjectMember.user_id == principal.user_id)
        )
        if not role:
            raise HTTPException(status_code=404, detail="Project not found")
    if write and role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="You have read-only access to this project")
    return project, role


async def project_view(db: AsyncSession, project: Project, role: str) -> dict:
    stats = (
        await db.execute(
            select(func.coalesce(func.sum(Message.cost_usd), 0.0), func.count(Message.id)).where(Message.project_id == project.id)
        )
    ).one()
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "prompt": project.prompt,
        "template": project.template,
        "template_label": TEMPLATES[project.template]["label"],
        "stack": project.stack,
        "generation_status": project.generation_status,
        "deployment_status": project.deployment_status,
        "github_repo": project.github_repo,
        "app_config": project.app_config,
        "has_code": bool(project.head_sha),
        "head_sha": project.head_sha,
        "estimated_usage_usd": round(float(stats[0]), 6),
        "message_count": int(stats[1]),
        "your_role": role,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def audit(db: AsyncSession, principal: Principal, action: str, target_type: str, target_id: str) -> None:
    db.add(
        AuditEvent(
            organization_id=principal.organization_id,
            actor_id=principal.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome="success",
        )
    )


async def ensure_user(db: AsyncSession, principal: Principal) -> None:
    # Development identities are seeded at startup; OIDC identities are persisted on sign-in.
    if not await db.get(User, principal.user_id):
        raise HTTPException(status_code=401, detail="Unknown user")


@router.get("/templates")
async def templates(_: Principal = Depends(get_principal)) -> list[dict]:
    return [{"id": key, **value} for key, value in TEMPLATES.items()]


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    query = select(Project).where(Project.organization_id == principal.organization_id)
    if principal.role not in {"owner", "admin"}:
        query = query.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == principal.user_id)
    projects = list(await db.scalars(query.order_by(Project.updated_at.desc())))
    roles = {}
    if principal.role not in {"owner", "admin"}:
        roles = dict(
            (await db.execute(select(ProjectMember.project_id, ProjectMember.role).where(ProjectMember.user_id == principal.user_id))).all()
        )
    return [await project_view(db, p, roles.get(p.id, "owner")) for p in projects]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    if principal.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot create projects")
    await ensure_user(db, principal)
    template = data.template or infer_template(data.prompt)
    project = Project(
        organization_id=principal.organization_id,
        owner_id=principal.user_id,
        name=data.name or derive_name(data.prompt),
        description=data.prompt,
        prompt=data.prompt,
        template=template,
        stack=TEMPLATES[template]["stack"],
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=principal.user_id, role="owner"))
    db.add(Conversation(project_id=project.id, organization_id=principal.organization_id))
    audit(db, principal, "project.create", "project", str(project.id))
    await db.commit()
    await db.refresh(project)
    return await project_view(db, project, "owner")


@router.get("/projects/{project_id}")
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> dict:
    project, role = await project_access(db, project_id, principal)
    return await project_view(db, project, role)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> dict:
    project, role = await project_access(db, project_id, principal, write=True)
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.template is not None:
        project.template = data.template
        project.stack = TEMPLATES[data.template]["stack"]
    if data.app_config is not None:
        if len(str(data.app_config)) > 20_000:
            raise HTTPException(status_code=422, detail="Configuration is too large")
        project.app_config = data.app_config
    project.updated_at = datetime.now(UTC)
    audit(db, principal, "project.update", "project", str(project.id))
    await db.commit()
    await db.refresh(project)
    return await project_view(db, project, role)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    confirm_name: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Response:
    project, role = await project_access(db, project_id, principal, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can delete a project")
    if confirm_name != project.name:
        raise HTTPException(status_code=422, detail="Type the project name to confirm deletion")
    if await db.scalar(select(Deployment.id).where(Deployment.project_id == project.id, Deployment.status.in_(["live", "deploying"]))):
        raise HTTPException(status_code=409, detail="This project has live deployments. Remove the App Platform app from your DigitalOcean account first.")
    for active in await db.scalars(select(GenerationRun.id).where(GenerationRun.project_id == project.id, GenerationRun.status.in_(["queued", "running"]))):
        await pipeline.cancel(active)
    for model in (Deployment, Approval, Checkpoint, GenerationRun, Message, AgentExecution, ProjectEnvVar, Conversation, ProjectMember):
        for row in await db.scalars(select(model).where(model.project_id == project.id)):
            await db.delete(row)
        await db.flush()
    token = project.preview_token
    await db.delete(project)
    audit(db, principal, "project.delete", "project", str(project_id))
    await db.commit()
    if token:
        await preview.remove(settings, token)
    ProjectStore(settings, project_id).remove()
    return Response(status_code=204)


def message_view(message: Message) -> dict:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "agent": message.agent,
        "model": message.model,
        "tier": message.tier,
        "input_tokens": message.input_tokens,
        "output_tokens": message.output_tokens,
        "cost_usd": message.cost_usd,
        "development_model": message.development_model,
        "created_at": message.created_at.isoformat(),
    }


@router.get("/projects/{project_id}/messages")
async def list_messages(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    messages = await db.scalars(select(Message).where(Message.project_id == project.id).order_by(Message.created_at))
    return [message_view(m) for m in messages]


@router.post("/projects/{project_id}/messages")
async def send_message(
    project_id: uuid.UUID,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    conversation = await db.scalar(select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.created_at))
    if not conversation:
        conversation = Conversation(project_id=project.id, organization_id=project.organization_id)
        db.add(conversation)
        await db.flush()
    history = list(
        await db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(20))
    )[::-1]
    user_message = Message(
        conversation_id=conversation.id,
        project_id=project.id,
        organization_id=project.organization_id,
        author_id=principal.user_id,
        role="user",
        content=data.content,
    )
    db.add(user_message)
    request_id = data.request_id or uuid.uuid4().hex
    execution = AgentExecution(
        project_id=project.id,
        organization_id=project.organization_id,
        agent="requirements",
        stage="requirements",
        status="running",
        request_id=request_id,
    )
    db.add(execution)
    if project.generation_status == "draft":
        project.generation_status = "planning"
    await db.commit()

    payload = {
        "messages": [
            {"role": "system", "content": REQUIREMENTS_SYSTEM_PROMPT},
            *({"role": m.role, "content": m.content} for m in history if m.role in {"user", "assistant"}),
            {"role": "user", "content": data.content},
        ],
        "agent": "requirements",
        "request_id": request_id,
        "max_output_tokens": 1200,
    }
    if data.tier:
        payload["tier"] = data.tier
    try:
        result = await gateway.call(settings, principal, "POST", "/v1/chat", project_id=project.id, json=payload)
    except HTTPException as exc:
        execution.status = "cancelled" if exc.status_code == 499 else "failed"
        detail = exc.detail if isinstance(exc.detail, str) else exc.detail.get("message", "Model request failed")
        execution.detail = str(detail)[:500]
        execution.attempts = exc.detail.get("attempts", []) if isinstance(exc.detail, dict) else []
        execution.finished_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=execution.detail) from exc

    usage = result["usage"]
    model = f"{result['provider']}/{result['model_id']}"
    assistant = Message(
        conversation_id=conversation.id,
        project_id=project.id,
        organization_id=project.organization_id,
        role="assistant",
        content=result["content"],
        agent="requirements",
        model=model,
        tier=result["tier"],
        request_id=request_id,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cost_usd=usage["cost_usd"],
        development_model=result["development_model"],
    )
    db.add(assistant)
    execution.status = "succeeded"
    execution.model = model
    execution.cost_usd = usage["cost_usd"]
    execution.attempts = result["attempts"]
    execution.finished_at = datetime.now(UTC)
    project.updated_at = datetime.now(UTC)
    await db.commit()
    return {
        "user_message": message_view(user_message),
        "assistant_message": message_view(assistant),
        "alerts": result.get("alerts", []),
        "attempts": result["attempts"],
    }


@router.post("/projects/{project_id}/requests/{request_id}/cancel")
async def cancel_request(
    project_id: uuid.UUID,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    owned = await db.scalar(
        select(AgentExecution.id).where(AgentExecution.project_id == project.id, AgentExecution.request_id == request_id)
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Request not found")
    return await gateway.call(settings, principal, "POST", f"/v1/requests/{request_id}/cancel", project_id=project.id)


@router.get("/projects/{project_id}/executions")
async def list_executions(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    rows = await db.scalars(
        select(AgentExecution).where(AgentExecution.project_id == project.id).order_by(AgentExecution.started_at.desc()).limit(50)
    )
    return [
        {
            "id": str(r.id),
            "agent": r.agent,
            "stage": r.stage,
            "status": r.status,
            "model": r.model,
            "cost_usd": r.cost_usd,
            "detail": r.detail,
            "attempts": r.attempts,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


@router.get("/projects/{project_id}/usage")
async def project_usage(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)
) -> dict:
    project, _ = await project_access(db, project_id, principal)
    return await gateway.call(settings, principal, "GET", "/v1/usage", project_id=project.id)


@router.put("/projects/{project_id}/budget")
async def project_budget(
    project_id: uuid.UUID,
    data: BudgetInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    project, role = await project_access(db, project_id, principal, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can change the budget")
    audit(db, principal, "project.budget.update", "project", str(project.id))
    await db.commit()
    return await gateway.call(settings, principal, "PUT", "/v1/budgets", project_id=project.id, json={"scope": "project", **data.model_dump()})


@router.get("/projects/{project_id}/model-preferences")
async def get_project_preferences(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)
) -> dict:
    project, _ = await project_access(db, project_id, principal)
    return await gateway.call(settings, principal, "GET", "/v1/preferences", project_id=project.id)


@router.put("/projects/{project_id}/model-preferences")
async def put_project_preferences(
    project_id: uuid.UUID,
    data: PreferenceInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    return await gateway.call(settings, principal, "PUT", "/v1/preferences", project_id=project.id, json=data.model_dump())


@router.get("/projects/{project_id}/members")
async def list_members(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    rows = await db.execute(
        select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == project.id)
    )
    return [
        {"user_id": str(user.id), "email": user.email, "display_name": user.display_name, "role": member.role}
        for member, user in rows.all()
    ]


@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: uuid.UUID, data: MemberCreate, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> dict:
    project, role = await project_access(db, project_id, principal, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can manage collaborators")
    user = await db.scalar(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(func.lower(User.email) == data.email.lower(), Membership.organization_id == principal.organization_id)
    )
    if not user:
        raise HTTPException(status_code=404, detail="No one in your organization has that email address")
    existing = await db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    if existing:
        raise HTTPException(status_code=409, detail="That person is already a collaborator")
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=data.role))
    audit(db, principal, "project.member.add", "project", str(project.id))
    await db.commit()
    return {"user_id": str(user.id), "email": user.email, "display_name": user.display_name, "role": data.role}


@router.delete("/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> Response:
    project, role = await project_access(db, project_id, principal, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only project owners can manage collaborators")
    if user_id == project.owner_id:
        raise HTTPException(status_code=409, detail="The project owner cannot be removed")
    member = await db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id))
    if not member:
        raise HTTPException(status_code=404, detail="Collaborator not found")
    await db.delete(member)
    audit(db, principal, "project.member.remove", "project", str(project.id))
    await db.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/env")
async def list_env(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)) -> list[dict]:
    project, _ = await project_access(db, project_id, principal)
    rows = await db.scalars(select(ProjectEnvVar).where(ProjectEnvVar.project_id == project.id).order_by(ProjectEnvVar.key))
    # Values are write-only: they are decrypted only when injected into an approved runtime.
    return [{"key": r.key, "environment": r.environment, "updated_at": r.updated_at.isoformat()} for r in rows]


@router.put("/projects/{project_id}/env")
async def put_env(
    project_id: uuid.UUID,
    data: EnvVarInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    project, _ = await project_access(db, project_id, principal, write=True)
    if not ENV_KEY.match(data.key):
        raise HTTPException(status_code=422, detail="Use upper-case letters, digits, and underscores, starting with a letter")
    row = await db.scalar(
        select(ProjectEnvVar).where(
            ProjectEnvVar.project_id == project.id, ProjectEnvVar.environment == data.environment, ProjectEnvVar.key == data.key
        )
    ) or ProjectEnvVar(project_id=project.id, organization_id=project.organization_id, environment=data.environment, key=data.key)
    row.encrypted_value = encrypt_secret(data.value.get_secret_value(), settings)
    row.updated_at = datetime.now(UTC)
    db.add(row)
    audit(db, principal, "project.env.update", "project", str(project.id))
    await db.commit()
    return {"key": row.key, "environment": row.environment, "updated_at": row.updated_at.isoformat()}


@router.delete("/projects/{project_id}/env/{environment}/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_env(
    project_id: uuid.UUID, environment: str, key: str, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> Response:
    project, _ = await project_access(db, project_id, principal, write=True)
    row = await db.scalar(
        select(ProjectEnvVar).where(ProjectEnvVar.project_id == project.id, ProjectEnvVar.environment == environment, ProjectEnvVar.key == key)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Variable not found")
    await db.delete(row)
    audit(db, principal, "project.env.delete", "project", str(project.id))
    await db.commit()
    return Response(status_code=204)


@router.get("/ai/providers")
async def ai_providers(principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> list:
    return await gateway.call(settings, principal, "GET", "/v1/providers")


@router.put("/ai/credentials/{provider}")
async def ai_put_credential(
    provider: str,
    data: CredentialInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    body = {"base_url": data.base_url, "api_key": data.api_key.get_secret_value() if data.api_key else None}
    result = await gateway.call(settings, principal, "PUT", f"/v1/credentials/{provider}", json=body)
    audit(db, principal, "ai.credential.update", "provider", provider)
    await db.commit()
    return result


@router.delete("/ai/credentials/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def ai_delete_credential(
    provider: str, db: AsyncSession = Depends(get_db), principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)
) -> Response:
    await gateway.call(settings, principal, "DELETE", f"/v1/credentials/{provider}")
    audit(db, principal, "ai.credential.delete", "provider", provider)
    await db.commit()
    return Response(status_code=204)


@router.post("/ai/registry/refresh")
async def ai_refresh(principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)) -> dict:
    return await gateway.call(settings, principal, "POST", "/v1/registry/refresh", timeout=60)


@router.get("/ai/models")
async def ai_models(
    provider: str | None = None, routable_only: bool = False, principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)
) -> list:
    params = {"routable_only": str(routable_only).lower()}
    if provider:
        params["provider"] = provider
    return await gateway.call(settings, principal, "GET", "/v1/models", params=params)


@router.get("/ai/tiers")
async def ai_tiers(principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> list:
    return await gateway.call(settings, principal, "GET", "/v1/tiers")


@router.get("/ai/usage")
async def ai_usage(principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    return await gateway.call(settings, principal, "GET", "/v1/usage")


@router.put("/ai/budget")
async def ai_budget(data: BudgetInput, principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)) -> dict:
    return await gateway.call(settings, principal, "PUT", "/v1/budgets", json={"scope": "organization_monthly", **data.model_dump()})


@router.get("/ai/preferences")
async def ai_get_preferences(principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    return await gateway.call(settings, principal, "GET", "/v1/preferences")


@router.put("/ai/preferences")
async def ai_put_preferences(data: PreferenceInput, principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)) -> dict:
    return await gateway.call(settings, principal, "PUT", "/v1/preferences", json=data.model_dump())
