"""Administrator-run benchmarks with deterministic graders.

Benchmarks call real models through the gateway, so they need a platform administrator, an
explicit billable confirmation, and a spending cap. Results are shown to administrators; they
never feed routing statistics or policy automatically.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .database import SessionLocal
from .inference_gateway import Gateway, GatewayError
from .model_registry import ModelView
from .models import BenchmarkRun
from .security import Caller, redact
from .validation_engine import parse_json

logger = logging.getLogger("aaee.benchmarks")
MAX_OUTPUT_TOKENS = 1_200


@dataclass(frozen=True)
class Case:
    name: str
    task_type: str
    system: str
    user: str
    grade: Callable[[str], tuple[bool, str]]


def _json(content: str):
    try:
        return parse_json(content)
    except ValueError:
        return None


def _grade_spec(content: str) -> tuple[bool, str]:
    value = _json(content)
    if not isinstance(value, dict) or not isinstance(value.get("entities"), list):
        return False, "No entities array"
    names = {str(e.get("name", "")).lower() for e in value["entities"] if isinstance(e, dict)}
    fields = {str(f.get("name", "")).lower() for e in value["entities"] if isinstance(e, dict) for f in e.get("fields") or [] if isinstance(f, dict)}
    if not any("task" in n for n in names):
        return False, "Missing a task entity"
    if not any("due" in f for f in fields):
        return False, "Missing a due date field"
    return True, "Valid specification"


def _grade_files(path: str, must: str, must_not: str) -> Callable[[str], tuple[bool, str]]:
    def grade(content: str) -> tuple[bool, str]:
        value = _json(content)
        files = value.get("files") if isinstance(value, dict) else None
        if not isinstance(files, list):
            return False, "No files array"
        match = next((f for f in files if isinstance(f, dict) and f.get("path") == path), None)
        if not match or not isinstance(match.get("content"), str):
            return False, f"{path} not returned"
        text = match["content"].replace(" ", "")
        if must.replace(" ", "") not in text or must_not.replace(" ", "") in text:
            return False, "The fix is incorrect"
        return True, "Correct patch"

    return grade


FILES_CONTRACT = 'Respond with JSON only: {"files": [{"path": "...", "content": "<complete file>"}], "summary": "..."}.'
SUITES: dict[str, list[Case]] = {
    "core-v1": [
        Case(
            "spec.todo",
            "architecture_design",
            'Return JSON only: {"entities": [{"name": "...", "fields": [{"name": "...", "type": "..."}]}]}.',
            "Design the data model for a to-do app where people track tasks with a title and a due date.",
            _grade_spec,
        ),
        Case(
            "edit.typescript",
            "incremental_code_edit",
            FILES_CONTRACT,
            "src/math.ts currently contains:\nexport const add = (a: number, b: number) => a - b;\n\nFix add so it returns the sum.",
            _grade_files("src/math.ts", "a + b", "a - b"),
        ),
        Case(
            "debug.python",
            "debugging",
            FILES_CONTRACT,
            "app/totals.py contains:\ndef total(items):\n    return sum(items) + 1\n\nThis test fails: assert total([1, 2]) == 3. Fix the bug.",
            _grade_files("app/totals.py", "return sum(items)", "sum(items) + 1"),
        ),
    ]
}


def worst_case_usd(model: ModelView, case: Case) -> float | None:
    if model.input_usd_per_mtok is None or model.output_usd_per_mtok is None:
        return None
    input_tokens = (len(case.system) + len(case.user)) // 3 + 50
    return (input_tokens * model.input_usd_per_mtok + MAX_OUTPUT_TOKENS * model.output_usd_per_mtok) / 1_000_000


async def run(run_id: uuid.UUID, identity: Caller, gateway: Gateway, models: list[ModelView]) -> None:
    async with SessionLocal() as db:
        record = await db.get(BenchmarkRun, run_id)
        suite, budget = SUITES[record.suite], record.budget_usd
        record.status = "running"
        await db.commit()
    spent, results, status = 0.0, [], "failed"
    try:
        for model in models:
            row = {"key": model.key, "family": model.family, "cases": [], "passed": 0, "cost_usd": 0.0, "skipped": None}
            for case in suite:
                worst = worst_case_usd(model, case)
                if worst is None:
                    row["skipped"] = "Pricing is unknown; supply validated pricing first"
                    break
                if spent + worst > budget:
                    row["skipped"] = "The benchmark budget cap was reached"
                    break
                started = datetime.now(UTC)
                try:
                    reply = await gateway.chat(
                        identity,
                        None,
                        model=model.key,
                        messages=[{"role": "system", "content": case.system}, {"role": "user", "content": case.user}],
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        task_budget_usd=worst,
                        response_format={"type": "json_object"} if "structured_output" in model.capabilities else None,
                        request_id=uuid.uuid4().hex,
                        attribution={"task_id": str(run_id), "execution_id": case.name, "strategy": "benchmark", "agent": "aaee:benchmark"},
                    )
                except GatewayError as exc:
                    row["cases"].append({"case": case.name, "passed": False, "detail": redact(str(exc))[:200], "cost_usd": 0.0})
                    continue
                passed, detail = case.grade(reply.content)
                spent += reply.cost_usd
                row["cost_usd"] += reply.cost_usd
                row["passed"] += passed
                row["cases"].append(
                    {
                        "case": case.name,
                        "passed": passed,
                        "detail": detail,
                        "cost_usd": round(reply.cost_usd, 6),
                        "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
                        "development_model": reply.development_model,
                    }
                )
            row["cost_usd"] = round(row["cost_usd"], 6)
            row["cost_per_pass_usd"] = round(row["cost_usd"] / row["passed"], 6) if row["passed"] else None
            results.append(row)
        status = "completed"
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception:
        logger.exception("benchmark %s failed", run_id)
    finally:
        async with SessionLocal() as db:
            record = await db.get(BenchmarkRun, run_id)
            record.status = status
            record.results = json.loads(json.dumps(results))
            record.spent_usd = round(spent, 6)
            record.finished_at = datetime.now(UTC)
            await db.commit()
