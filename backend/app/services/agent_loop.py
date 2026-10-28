"""Bounded, authorized software-agent tool loop.

The model proposes one action at a time. This module validates every argument, executes only
inside a project repository or its isolated sandbox, returns the result, and checkpoints only
after required checks pass. It never exposes host credentials or a Docker socket.
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from ..builder import toolchain
from ..builder.sandbox import Job, run
from ..builder.store import ProjectStore, StoreError, clean_path
from ..config import Settings

TOOLS = {
    "read_file",
    "search_code",
    "apply_patch",
    "run_command",
    "run_tests",
    "inspect_build_logs",
    "git_diff",
}
DENIED_COMMANDS = re.compile(
    r"\b(curl|wget|ssh|scp|nc|ncat|sudo|mount|umount|docker|podman|terraform|doctl)\b"
)
MAX_RESULT = 60_000


class ToolDenied(ValueError):
    pass


@dataclass
class LoopLimits:
    max_steps: int = 12
    max_seconds: float = 300
    maximum_cost_usd: float = 1


@dataclass
class LoopResult:
    status: str
    answer: str
    steps: list[dict]
    cost_usd: float
    checkpoint_sha: str | None = None


NextAction = Callable[[list[dict], float], Awaitable[dict]]


class WorkspaceTools:
    def __init__(
        self,
        settings: Settings,
        store: ProjectStore,
        *,
        allowed_paths: list[str],
        allowed_commands: list[str],
        logs: dict[str, str] | None = None,
    ):
        self.settings = settings
        self.store = store
        self.allowed_paths = allowed_paths
        self.allowed_commands = set(allowed_commands)
        self.logs = logs or {}

    def path(self, raw: str) -> str:
        path = clean_path(raw)
        if self.allowed_paths and not any(
            path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
            for prefix in self.allowed_paths
        ):
            raise ToolDenied("Path is outside this task's authorized paths")
        return path

    async def execute(self, name: str, arguments: dict) -> dict:
        if name not in TOOLS:
            raise ToolDenied("Unknown tool")
        if name == "read_file":
            path = self.path(str(arguments.get("path", "")))
            return {"path": path, "content": self.store.read(path)[:MAX_RESULT]}
        if name == "search_code":
            query = str(arguments.get("query", ""))
            if not query or len(query) > 200:
                raise ToolDenied("Search query must be 1–200 characters")
            root = str(arguments.get("path", ""))
            root = self.path(root) if root else ""
            matches = []
            for path in self.store.working_files():
                if root and not path.startswith(root):
                    continue
                try:
                    for number, line in enumerate(self.store.read(path).splitlines(), 1):
                        if query.lower() in line.lower():
                            matches.append({"path": path, "line": number, "text": line[:500]})
                            if len(matches) >= 200:
                                return {"matches": matches, "truncated": True}
                except (StoreError, UnicodeDecodeError):
                    continue
            return {"matches": matches, "truncated": False}
        if name == "apply_patch":
            path = self.path(str(arguments.get("path", "")))
            before, after = arguments.get("before"), arguments.get("after")
            if not isinstance(before, str) or not isinstance(after, str):
                raise ToolDenied("Patch needs exact before and after strings")
            current = self.store.read(path)
            if current.count(before) != 1:
                raise ToolDenied("Patch anchor must occur exactly once")
            self.store.write(path, current.replace(before, after, 1))
            self.store.adopt(path)
            return {"path": path, "changed": True}
        if name in {"run_command", "run_tests"}:
            command = arguments.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(item, str) and len(item) <= 1_000 for item in command)
            ):
                raise ToolDenied("Command must be a non-empty argv array")
            executable = Path(command[0]).name
            if executable not in self.allowed_commands or DENIED_COMMANDS.search(" ".join(command)):
                raise ToolDenied("Command is not authorized")
            sandbox_result = await run(
                self.settings,
                Job(
                    command=command,
                    app_dir=self.store.repo,
                    timeout=min(float(arguments.get("timeout", 120)), 300),
                ),
                toolchain.toolchain_dir(self.settings),
            )
            return {
                "exit_code": sandbox_result.exit_code,
                "output": sandbox_result.output[-MAX_RESULT:],
                "duration": sandbox_result.duration,
                "timed_out": sandbox_result.timed_out,
            }
        if name == "inspect_build_logs":
            key = str(arguments.get("key", "latest"))
            return {"key": key, "content": self.logs.get(key, "No log was recorded.")[-MAX_RESULT:]}
        if name == "git_diff":
            process = await asyncio.create_subprocess_exec(
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "diff",
                "--",
                ".",
                ":(exclude).omniweb",
                cwd=self.store.repo,
                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await process.communicate()
            return {"diff": output.decode(errors="replace")[:MAX_RESULT]}
        raise ToolDenied("Tool is not implemented")


async def run_loop(
    next_action: NextAction,
    tools: WorkspaceTools,
    limits: LoopLimits,
    *,
    required_tests: list[list[str]],
    checkpoint_message: str,
) -> LoopResult:
    started = time.monotonic()
    history: list[dict] = []
    steps: list[dict] = []
    cost = 0.0
    answer = ""
    status = "failed"
    for index in range(limits.max_steps):
        if time.monotonic() - started >= limits.max_seconds:
            status, answer = "budget_exhausted", "The agent reached its time budget."
            break
        action = await next_action(history, limits.maximum_cost_usd - cost)
        reported = max(0.0, float(action.get("cost_usd", 0)))
        if cost + reported > limits.maximum_cost_usd:
            status, answer = "budget_exhausted", "The next model action exceeds the cost budget."
            break
        cost += reported
        if action.get("type") == "final":
            status, answer = "ready_for_validation", str(action.get("content", ""))[:20_000]
            break
        if action.get("type") != "tool":
            status, answer = "failed", "The model returned an invalid action."
            break
        name, arguments = action.get("tool"), action.get("arguments")
        try:
            result = await tools.execute(name, arguments if isinstance(arguments, dict) else {})
            event = {"step": index + 1, "tool": name, "arguments": arguments, "result": result}
        except (ToolDenied, StoreError) as exc:
            event = {
                "step": index + 1,
                "tool": name,
                "arguments": arguments,
                "error": str(exc),
            }
        steps.append(event)
        history.append({"role": "assistant", "content": json.dumps(action)})
        history.append({"role": "tool", "content": json.dumps(event, default=str)})
    if status != "ready_for_validation":
        return LoopResult(status, answer, steps, round(cost, 6))
    for command in required_tests:
        result = await tools.execute("run_tests", {"command": command, "timeout": 300})
        steps.append(
            {
                "step": len(steps) + 1,
                "tool": "run_tests",
                "arguments": {"command": command},
                "result": result,
            }
        )
        if result["exit_code"] != 0 or result["timed_out"]:
            return LoopResult(
                "validation_failed",
                "Required checks failed; no checkpoint was created.",
                steps,
                round(cost, 6),
            )
    sha = await tools.store.commit(checkpoint_message[:300], "agent")
    return LoopResult("completed", answer, steps, round(cost, 6), sha)
