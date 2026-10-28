"""Task-level usage ledger.

Every LLM call also lands in the gateway's per-call ledger; this ledger adds the task,
attempt, strategy, and non-gateway costs (tools). Usage is keyed by an idempotency
key, so a retried report never charges twice. Customer-key (BYOK) usage is recorded but is
never counted as Omniweb's own provider expense.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import Execution, Task, UsageEvent


def billing_split(cost_usd: float, billing_model: str, settings: Settings) -> tuple[float, float]:
    """Return (Omniweb provider expense, amount billable to the customer)."""
    if billing_model == "customer":
        return 0.0, settings.byok_platform_fee_usd_per_execution
    if billing_model == "none":
        return 0.0, 0.0
    return cost_usd, round(cost_usd * (1 + settings.platform_markup), 8)


async def record(
    db: AsyncSession,
    task: Task,
    execution: Execution,
    *,
    idempotency_key: str,
    source: str,
    billing_model: str,
    settings: Settings,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    cost_usd: float = 0.0,
    reported_cost_usd: float | None = None,
    details: dict | None = None,
) -> UsageEvent | None:
    existing = await db.scalar(select(UsageEvent).where(UsageEvent.tenant_id == task.tenant_id, UsageEvent.idempotency_key == idempotency_key))
    if existing:
        return None
    event = UsageEvent(
        idempotency_key=idempotency_key,
        tenant_id=task.tenant_id,
        execution_id=execution.id,
        source=source,
        billing_model=billing_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_usd=round(cost_usd, 8),
        reported_cost_usd=reported_cost_usd,
        details=details or {},
    )
    db.add(event)
    execution.input_tokens += input_tokens
    execution.output_tokens += output_tokens
    execution.cached_tokens += cached_tokens
    if source == "tool":
        execution.infra_cost_usd = round(execution.infra_cost_usd + cost_usd, 8)
    else:
        execution.inference_cost_usd = round(execution.inference_cost_usd + cost_usd, 8)
    execution.total_cost_usd = round(execution.inference_cost_usd + execution.infra_cost_usd, 8)
    if reported_cost_usd is not None:
        execution.actual_reported_cost_usd = round((execution.actual_reported_cost_usd or 0) + reported_cost_usd, 8)
    if execution.billing_model in ("none", "") or billing_model == "customer":
        execution.billing_model = billing_model
    provider_cost, billable = billing_split(cost_usd, billing_model, settings)
    execution.provider_cost_usd = round(execution.provider_cost_usd + provider_cost, 8)
    execution.customer_billable_usd = round(execution.customer_billable_usd + billable, 8)
    task.total_cost_usd = round(task.total_cost_usd + cost_usd, 8)
    await db.flush()
    return event


def mark_retry_cost(task: Task, execution: Execution) -> None:
    """Cost of an attempt that did not produce the accepted result."""
    task.retry_cost_usd = round(task.retry_cost_usd + execution.total_cost_usd, 8)
