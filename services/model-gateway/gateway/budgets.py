import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import Budget, BudgetAlert, UsageRecord

ORG_MONTHLY = "organization_monthly"
PROJECT = "project"


def month_start(at: datetime | None = None) -> datetime:
    at = at or datetime.now(UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def period_key(at: datetime | None = None) -> str:
    return (at or datetime.now(UTC)).strftime("%Y-%m")


@dataclass
class BudgetState:
    budget: Budget
    spent_usd: float

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.budget.limit_usd - self.spent_usd)


async def get_or_default(
    db: AsyncSession, organization_id: uuid.UUID, scope: str, scope_id: str, settings: Settings
) -> Budget:
    budget = await db.scalar(
        select(Budget).where(
            Budget.organization_id == organization_id, Budget.scope == scope, Budget.scope_id == scope_id
        )
    )
    if budget:
        return budget
    limit = settings.default_monthly_budget_usd if scope == ORG_MONTHLY else settings.default_project_budget_usd
    budget = Budget(
        organization_id=organization_id,
        scope=scope,
        scope_id=scope_id,
        limit_usd=limit,
        hard_limit=True,
        alert_threshold=settings.alert_threshold,
    )
    db.add(budget)
    await db.flush()
    return budget


async def spent(db: AsyncSession, organization_id: uuid.UUID, project_id: uuid.UUID | None = None) -> float:
    query = select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
        UsageRecord.organization_id == organization_id
    )
    if project_id:
        query = query.where(UsageRecord.project_id == project_id)
    else:
        query = query.where(UsageRecord.created_at >= month_start())
    return float(await db.scalar(query) or 0)


async def states(
    db: AsyncSession, organization_id: uuid.UUID, project_id: uuid.UUID | None, settings: Settings
) -> list[BudgetState]:
    result = [
        BudgetState(
            await get_or_default(db, organization_id, ORG_MONTHLY, str(organization_id), settings),
            await spent(db, organization_id),
        )
    ]
    if project_id:
        result.append(
            BudgetState(
                await get_or_default(db, organization_id, PROJECT, str(project_id), settings),
                await spent(db, organization_id, project_id),
            )
        )
    return result


def remaining(budget_states: list[BudgetState], task_budget_usd: float) -> float:
    hard = [state.remaining_usd for state in budget_states if state.budget.hard_limit]
    return min([task_budget_usd, *hard])


async def record_alerts(db: AsyncSession, budget_states: list[BudgetState]) -> list[str]:
    messages = []
    for state in budget_states:
        budget = state.budget
        label = "Monthly organization budget" if budget.scope == ORG_MONTHLY else "Project budget"
        kind = None
        if state.spent_usd >= budget.limit_usd:
            kind = "exhausted"
        elif state.spent_usd >= budget.limit_usd * budget.alert_threshold:
            kind = "threshold"
        if not kind:
            continue
        message = (
            f"{label} {'reached' if kind == 'exhausted' else f'passed {int(budget.alert_threshold * 100)}%'}: "
            f"${state.spent_usd:.4f} of ${budget.limit_usd:.2f}"
        )
        messages.append(message)
        try:
            async with db.begin_nested():
                db.add(
                    BudgetAlert(
                        budget_id=budget.id,
                        organization_id=budget.organization_id,
                        period=period_key() if budget.scope == ORG_MONTHLY else "lifetime",
                        kind=kind,
                        message=message,
                    )
                )
        except IntegrityError:
            pass
    return messages
