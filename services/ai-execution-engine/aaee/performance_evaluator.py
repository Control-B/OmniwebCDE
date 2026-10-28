"""Outcome statistics per strategy, model, task type, and complexity.

Success means the attempt passed validation. Statistics come only from validation outcomes
(including administrator-run benchmarks), never from user feedback, so untrusted feedback
cannot move global routing. The planner uses a Wilson lower bound, and only once a key has
the policy's minimum number of samples.
"""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .execution_planner import Observation
from .models import Execution, Task

WINDOW_DAYS = 90
MAX_ROWS = 20_000


def wilson_lower(successes: int, n: int, z: float = 1.645) -> float:
    if n == 0:
        return 0.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denominator)


class DbStats:
    def __init__(self, rows: list[tuple[str, str, str, str, bool, float, int]]):
        buckets: dict[tuple, list] = defaultdict(list)
        for level, key, task_type, complexity, passed, cost, duration in rows:
            buckets[(level, key, task_type, complexity)].append((passed, cost, duration))
        self.table: dict[tuple, Observation] = {}
        for bucket_key, outcomes in buckets.items():
            n = len(outcomes)
            successes = sum(1 for passed, _, _ in outcomes if passed)
            durations = sorted(d for _, _, d in outcomes if d)
            self.table[bucket_key] = Observation(
                samples=n,
                successes=successes,
                lower_bound=round(wilson_lower(successes, n), 4),
                mean_cost_usd=sum(c for _, c, _ in outcomes) / n,
                p50_latency_ms=durations[len(durations) // 2] if durations else None,
            )

    def lookup(self, level: str, key: str, task_type: str, complexity: str) -> Observation | None:
        return self.table.get((level, key, task_type, complexity))

    def rows(self) -> list[dict]:
        return [
            {
                "level": k[0],
                "key": k[1],
                "task_type": k[2],
                "complexity": k[3],
                "samples": o.samples,
                "successes": o.successes,
                "success_rate": round(o.successes / o.samples, 4),
                "wilson_lower": o.lower_bound,
                "mean_cost_usd": round(o.mean_cost_usd, 6),
                "p50_latency_ms": o.p50_latency_ms,
            }
            for k, o in sorted(self.table.items(), key=lambda item: (-item[1].samples, item[0]))
        ]


async def load(db: AsyncSession, tenant_id=None) -> DbStats:
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    query = (
        select(Execution.candidate, Task.task_type, Task.complexity, Execution.validation, Execution.total_cost_usd, Execution.duration_ms)
        .join(Task, Task.id == Execution.task_id)
        .where(Execution.validation.in_(["passed", "failed"]), Execution.created_at >= since)
        .order_by(Execution.created_at.desc())
        .limit(MAX_ROWS)
    )
    if tenant_id:
        query = query.where(Execution.tenant_id == tenant_id)
    rows = []
    for candidate, task_type, complexity, validation, cost, duration in (await db.execute(query)).all():
        if not candidate or not candidate.get("key"):
            continue
        rows.append((candidate.get("level", ""), candidate["key"], task_type, complexity, validation == "passed", cost or 0.0, duration or 0))
    return DbStats(rows)
