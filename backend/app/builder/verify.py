"""Checks that decide whether a generated application works.

Every step runs inside the sandbox on an exported copy of the project. A build only counts as
verified when every required step exits successfully.
"""

import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import Settings
from . import sandbox, toolchain
from .store import ProjectStore

TSC = "/mnt/toolchain/node_modules/typescript/bin/tsc"
VITEST = "/mnt/toolchain/node_modules/vitest/vitest.mjs"
PREVIEW = "/mnt/toolchain/scripts/preview-build.mjs"


@dataclass
class Step:
    name: str
    label: str
    command: list[str]
    target: str


@dataclass
class StepResult:
    name: str
    label: str
    target: str
    ok: bool
    exit_code: int
    duration: float
    timed_out: bool
    output: str


def steps_for(targets: list[str], root: Path) -> list[Step]:
    steps: list[Step] = []
    if "web" in targets and (root / "apps/web/package.json").exists():
        steps += [
            Step("web.typecheck", "Type-check web app", ["node", TSC, "-p", "apps/web"], "web"),
            Step(
                "web.test",
                "Web unit tests",
                ["sh", "-c", f"cd apps/web && node {VITEST} run"],
                "web",
            ),
            Step(
                "web.build",
                "Build web preview",
                ["node", PREVIEW, "web", "apps/web", "/mnt/app/.preview/web"],
                "web",
            ),
        ]
    if "api" in targets and (root / "services/api/app/main.py").exists():
        steps += [
            Step(
                "api.test",
                "API tests",
                ["sh", "-c", "cd services/api && python3 -m pytest -q -p no:cacheprovider"],
                "api",
            ),
            Step(
                "api.migrate",
                "Apply database migrations",
                [
                    "sh",
                    "-c",
                    "cd services/api && DATABASE_URL=sqlite:////tmp/verify.db python3 -m alembic upgrade head",
                ],
                "api",
            ),
        ]
    if "mobile" in targets and (root / "apps/mobile/package.json").exists():
        steps.append(
            Step(
                "mobile.build",
                "Build mobile preview (React Native Web)",
                ["node", PREVIEW, "mobile", "apps/mobile", "/mnt/app/.preview/mobile"],
                "mobile",
            )
        )
    return steps


def build_dir(settings: Settings, run_id: uuid.UUID | str) -> Path:
    return toolchain.data_dir(settings) / "builds" / str(run_id)


async def run_checks(
    settings: Settings,
    store: ProjectStore,
    targets: list[str],
    run_id: uuid.UUID | str,
    on_step=None,
) -> tuple[list[StepResult], Path]:
    """Exports the worktree, runs every check, and returns results plus the build directory."""
    tc = await toolchain.ensure(settings)
    root = store.export(build_dir(settings, run_id))
    for app in ("apps/web", "apps/mobile"):
        if (root / app).is_dir():
            sandbox.link_node_modules(root / app, tc)
    results: list[StepResult] = []
    for step in steps_for(targets, root):
        if on_step:
            await on_step(step, None)
        outcome = await sandbox.run(settings, sandbox.Job(command=step.command, app_dir=root), tc)
        result = StepResult(
            step.name,
            step.label,
            step.target,
            outcome.ok,
            outcome.exit_code,
            round(outcome.duration, 2),
            outcome.timed_out,
            outcome.output[-12_000:],
        )
        results.append(result)
        if on_step:
            await on_step(step, result)
    return results, root


def summarize(results: list[StepResult]) -> dict:
    return {
        "ok": bool(results) and all(r.ok for r in results),
        "steps": [asdict(r) for r in results],
        "failed": [r.name for r in results if not r.ok],
        "duration": round(sum(r.duration for r in results), 2),
    }


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
