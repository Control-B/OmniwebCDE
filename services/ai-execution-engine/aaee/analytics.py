"""Routing analytics: what successful work cost, and which routes earned it.

Every figure comes from the ledger and validation outcomes recorded here. Costs are AAEE's
estimates and gateway-reported charges; they are not provider invoices, and "savings" compares
against an estimated baseline, not a measured counterfactual.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Execution, Feedback, Task

TERMINAL_OUTCOMES = {"completed", "failed", "needs_human", "cancelled", "blocked"}


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _group() -> dict:
    return {"tasks": 0, "completed": 0, "cost_usd": 0.0}


async def routing_analytics(db: AsyncSession, tenant_id: uuid.UUID | None, days: int = 30) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    task_query = select(Task).where(Task.created_at >= since, Task.caller != "benchmark")
    execution_query = select(Execution).where(Execution.created_at >= since, Execution.benchmark.is_(False))
    feedback_query = select(Feedback).where(Feedback.created_at >= since)
    if tenant_id:
        task_query = task_query.where(Task.tenant_id == tenant_id)
        execution_query = execution_query.where(Execution.tenant_id == tenant_id)
        feedback_query = feedback_query.where(Feedback.tenant_id == tenant_id)
    tasks = list(await db.scalars(task_query))
    executions = list(await db.scalars(execution_query))
    feedback = list(await db.scalars(feedback_query))

    finished = [t for t in tasks if t.status in TERMINAL_OUTCOMES]
    completed = [t for t in tasks if t.status == "completed"]
    total_cost = sum(t.total_cost_usd for t in tasks)
    retry_cost = sum(t.retry_cost_usd for t in tasks)
    by_task = defaultdict(list)
    for execution in executions:
        by_task[execution.task_id].append(execution)
    escalated = sum(1 for t in finished if len({e.strategy + (e.model_id or e.tool or "") for e in by_task.get(t.id, [])}) > 1)

    by_phase: dict[str, dict] = defaultdict(_group)
    by_type: dict[str, dict] = defaultdict(_group)
    for task in tasks:
        for bucket in (by_phase[task.spec.get("development_phase") or "unknown"], by_type[task.task_type]):
            bucket["tasks"] += 1
            bucket["cost_usd"] += task.total_cost_usd
            bucket["completed"] += task.status == "completed"

    by_strategy: dict[str, dict] = defaultdict(lambda: {"executions": 0, "passed": 0, "failed": 0, "cost_usd": 0.0})
    by_model: dict[str, dict] = defaultdict(lambda: {"executions": 0, "passed": 0, "failed": 0, "cost_usd": 0.0, "strategy": "", "family": None})
    billing = {"platform_provider_cost_usd": 0.0, "platform_billable_usd": 0.0, "customer_paid_inference_usd": 0.0, "customer_platform_fees_usd": 0.0}
    for execution in executions:
        key = f"{execution.provider}/{execution.model_id}" if execution.model_id else f"tool:{execution.tool or execution.strategy}"
        for bucket in (by_strategy[execution.strategy], by_model[key]):
            bucket["executions"] += 1
            bucket["passed"] += execution.validation == "passed"
            bucket["failed"] += execution.validation == "failed"
            bucket["cost_usd"] += execution.total_cost_usd
        by_model[key]["strategy"] = execution.strategy
        by_model[key]["family"] = execution.model_family
        if execution.billing_model == "customer":
            billing["customer_paid_inference_usd"] += execution.total_cost_usd
            billing["customer_platform_fees_usd"] += execution.customer_billable_usd
        else:
            billing["platform_provider_cost_usd"] += execution.provider_cost_usd
            billing["platform_billable_usd"] += execution.customer_billable_usd

    shadow_total = shadow_agree = 0
    baseline = actual_for_baseline = 0.0
    for task in tasks:
        chosen = (task.plan.get("chosen") or {}).get("key")
        for shadow in task.plan.get("shadow") or []:
            shadow_total += 1
            shadow_agree += shadow.get("chosen") == chosen
        if task.status == "completed" and task.plan.get("baseline"):
            baseline += task.plan["baseline"]["expected_cost_usd"]
            actual_for_baseline += task.total_cost_usd

    def finish(groups: dict, success_key: str) -> list[dict]:
        rows = []
        for name, g in groups.items():
            rows.append(
                {
                    "name": name,
                    **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in g.items()},
                    "cost_per_success_usd": _ratio(g["cost_usd"], g[success_key]),
                }
            )
        return sorted(rows, key=lambda r: -r["cost_usd"])

    return {
        "window_days": days,
        "scope": "organization" if tenant_id else "platform",
        "summary": {
            "tasks": len(tasks),
            "finished": len(finished),
            "completed": len(completed),
            "success_rate": _ratio(len(completed), len(finished)),
            "total_cost_usd": round(total_cost, 6),
            "cost_per_success_usd": _ratio(total_cost, len(completed)),
            "retry_cost_usd": round(retry_cost, 6),
            "retry_cost_share": _ratio(retry_cost, total_cost),
            "escalation_rate": _ratio(escalated, len(finished)),
            "needs_human": sum(1 for t in tasks if t.status == "needs_human"),
            "deterministic_share": _ratio(by_strategy["deterministic"]["executions"], len(executions)) if executions else None,
        },
        "by_strategy": finish(by_strategy, "passed"),
        "by_model": finish(by_model, "passed")[:40],
        "by_phase": finish(by_phase, "completed"),
        "by_task_type": finish(by_type, "completed"),
        "billing": {k: round(v, 6) for k, v in billing.items()},
        "shadow": {"decisions": shadow_total, "agreement_rate": _ratio(shadow_agree, shadow_total)},
        "savings": {
            "baseline_estimated_usd": round(baseline, 6),
            "actual_usd": round(actual_for_baseline, 6),
            "estimated_savings_usd": round(baseline - actual_for_baseline, 6),
            "note": "Baseline: the strongest eligible hosted model on a single attempt, estimated with the same token model.",
        },
        "feedback": {
            "responses": len(feedback),
            "accepted": sum(1 for f in feedback if f.accepted),
            "regressions": sum(1 for f in feedback if f.regression),
            "note": "Feedback is reported for review. It never changes routing policy automatically.",
        },
        "disclaimer": "Estimated cost controls are not provider-enforced billing limits. Figures are AAEE ledger values, not provider invoices.",
    }
