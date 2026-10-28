"""Hierarchical budgets with reservations.

Scopes: platform, organization, project, user, task, and a per-attempt execution ceiling.
Organization and project limits and gateway-recorded spend come from the model gateway;
AAEE adds its outstanding reservations and the spend that never passes through the gateway
(engine and caller-side tools). Each attempt reserves its worst-case cost before it runs, inside
one serialized transaction (row locks on PostgreSQL, BEGIN IMMEDIATE on SQLite), so
concurrent tasks cannot together exceed a hard limit.

These are estimates enforced by Omniweb. They are not provider-enforced billing limits;
configure provider-side spend limits as well.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import Budget, BudgetAlert, BudgetCounter, BudgetReservation, Task

GATEWAY_SCOPES = {"organization_monthly": "organization", "project": "project"}


class BudgetExceeded(Exception):
    def __init__(self, scope: str, available: float, needed: float):
        super().__init__(f"{scope} budget: ${available:.4f} available, ${needed:.4f} needed")
        self.scope = scope
        self.available = available
        self.needed = needed


@dataclass
class ScopeState:
    scope: str
    scope_id: str
    period: str
    limit_usd: float
    used_usd: float  # spend plus outstanding reservations
    hard: bool
    alert_threshold: float

    @property
    def available(self) -> float:
        return max(0.0, self.limit_usd - self.used_usd) if self.hard else float("inf")


def month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def scope_keys(task: Task, billing_model: str) -> list[tuple[str, str, str]]:
    keys = [("organization", str(task.tenant_id), month()), ("task", str(task.id), "lifetime")]
    if billing_model != "customer":
        # Customer-paid (BYOK) inference is not Omniweb's expense, so it does not draw on the
        # platform budget. Organization, project, user, and task limits still apply.
        keys.insert(0, ("platform", "platform", month()))
    if task.project_id:
        keys.append(("project", str(task.project_id), "lifetime"))
    if task.user_id:
        keys.append(("user", str(task.user_id), month()))
    return keys


async def _counter(db: AsyncSession, scope: str, scope_id: str, period: str, lock: bool) -> BudgetCounter:
    query = select(BudgetCounter).where(BudgetCounter.scope == scope, BudgetCounter.scope_id == scope_id, BudgetCounter.period == period)
    if lock:
        query = query.with_for_update()
    counter = await db.scalar(query)
    if counter:
        return counter
    try:
        async with db.begin_nested():
            counter = BudgetCounter(scope=scope, scope_id=scope_id, period=period)
            db.add(counter)
    except IntegrityError:
        counter = await db.scalar(query)
    return counter


async def _limit(db: AsyncSession, scope: str, scope_id: str, task: Task, settings: Settings) -> tuple[float, bool, float]:
    if scope == "task":
        return task.spec["maximum_budget_usd"] + task.overage_approved_usd, True, settings.alert_threshold
    owner = Budget.tenant_id.is_(None) if scope == "platform" else Budget.tenant_id == task.tenant_id
    override = await db.scalar(
        select(Budget).where(Budget.scope == scope, Budget.scope_id.in_([scope_id, "default"]), owner).order_by(Budget.scope_id == "default").limit(1)
    )
    if override:
        return override.limit_usd, override.hard_limit, override.alert_threshold
    default = settings.platform_monthly_budget_usd if scope == "platform" else settings.user_monthly_budget_usd
    return default, True, settings.alert_threshold


async def states(db: AsyncSession, task: Task, billing_model: str, gateway_rows: list[dict], settings: Settings, lock: bool = False) -> list[ScopeState]:
    gateway = {GATEWAY_SCOPES[r["scope"]]: r for r in gateway_rows if r.get("scope") in GATEWAY_SCOPES}
    result = []
    for scope, scope_id, period in scope_keys(task, billing_model):
        counter = await _counter(db, scope, scope_id, period, lock)
        if scope in GATEWAY_SCOPES.values():
            row = gateway.get(scope)
            if not row:
                continue
            used = float(row["spent_usd"]) + counter.external_spent_usd + counter.reserved_usd
            result.append(
                ScopeState(
                    scope,
                    scope_id,
                    period,
                    float(row["limit_usd"]),
                    used,
                    bool(row.get("hard_limit", True)),
                    float(row.get("alert_threshold", settings.alert_threshold)),
                )
            )
        else:
            limit, hard, threshold = await _limit(db, scope, scope_id, task, settings)
            result.append(ScopeState(scope, scope_id, period, limit, counter.spent_usd + counter.reserved_usd, hard, threshold))
    return result


def available(scope_states: list[ScopeState], exclude: set[str] | None = None) -> float:
    values = [s.available for s in scope_states if s.scope not in (exclude or set())]
    return min(values) if values else float("inf")


def limiting(scope_states: list[ScopeState]) -> ScopeState | None:
    hard = [s for s in scope_states if s.hard]
    return min(hard, key=lambda s: s.available) if hard else None


async def reserve(
    db: AsyncSession,
    task: Task,
    execution_id: uuid.UUID,
    amount: float,
    *,
    billing_model: str,
    gateway_routed: bool,
    gateway_rows: list[dict],
    settings: Settings,
) -> BudgetReservation:
    """Must run in its own short transaction; the caller commits immediately afterwards."""
    amount = round(max(amount, 0.0), 8)
    scope_states = await states(db, task, billing_model, gateway_rows, settings, lock=True)
    for state in scope_states:
        if state.hard and amount > state.available + 1e-12:
            raise BudgetExceeded(state.scope, state.available, amount)
    keys = [[s.scope, s.scope_id, s.period] for s in scope_states]
    for scope, scope_id, period in keys:
        counter = await _counter(db, scope, scope_id, period, lock=True)
        counter.reserved_usd = round(counter.reserved_usd + amount, 8)
        counter.version += 1
    reservation = BudgetReservation(
        tenant_id=task.tenant_id, task_id=task.id, execution_id=execution_id, amount_usd=amount, scopes=keys, gateway_routed=gateway_routed
    )
    db.add(reservation)
    await db.flush()
    return reservation


async def settle(db: AsyncSession, reservation: BudgetReservation, actual_usd: float, settings: Settings, task: Task | None = None) -> list[str]:
    if reservation.status != "held":
        return []
    for scope, scope_id, period in reservation.scopes:
        counter = await _counter(db, scope, scope_id, period, lock=True)
        counter.reserved_usd = round(max(0.0, counter.reserved_usd - reservation.amount_usd), 8)
        counter.spent_usd = round(counter.spent_usd + actual_usd, 8)
        if not reservation.gateway_routed:
            counter.external_spent_usd = round(counter.external_spent_usd + actual_usd, 8)
        counter.version += 1
    reservation.status = "committed"
    reservation.actual_usd = round(actual_usd, 8)
    reservation.settled_at = datetime.now(UTC)
    await db.flush()
    return await alerts(db, reservation, settings, task) if task else []


async def release(db: AsyncSession, reservation: BudgetReservation) -> None:
    if reservation.status != "held":
        return
    for scope, scope_id, period in reservation.scopes:
        counter = await _counter(db, scope, scope_id, period, lock=True)
        counter.reserved_usd = round(max(0.0, counter.reserved_usd - reservation.amount_usd), 8)
        counter.version += 1
    reservation.status = "released"
    reservation.settled_at = datetime.now(UTC)
    await db.flush()


async def release_for_task(db: AsyncSession, task_id: uuid.UUID) -> None:
    for reservation in await db.scalars(select(BudgetReservation).where(BudgetReservation.task_id == task_id, BudgetReservation.status == "held")):
        await release(db, reservation)


async def alerts(db: AsyncSession, reservation: BudgetReservation, settings: Settings, task: Task) -> list[str]:
    messages = []
    for scope, scope_id, period in reservation.scopes:
        if scope in GATEWAY_SCOPES.values():
            continue  # the gateway raises organization and project alerts
        counter = await _counter(db, scope, scope_id, period, lock=False)
        limit, _hard, threshold = await _limit(db, scope, scope_id, task, settings)
        kind = "exhausted" if counter.spent_usd >= limit else "soft" if counter.spent_usd >= limit * threshold else None
        if not kind:
            continue
        message = f"{scope.title()} budget {'reached' if kind == 'exhausted' else f'passed {int(threshold * 100)}%'}: ${counter.spent_usd:.4f} of ${limit:.2f}"
        messages.append(message)
        try:
            async with db.begin_nested():
                db.add(
                    BudgetAlert(
                        tenant_id=None if scope == "platform" else task.tenant_id, scope=scope, scope_id=scope_id, period=period, kind=kind, message=message
                    )
                )
        except IntegrityError:
            pass
    return messages
