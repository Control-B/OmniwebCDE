"""Deterministic tools: strategy A. They cost nothing and are tried before any model.

Two kinds exist. Engine tools run inside AAEE on the task's input artifacts. Caller tools,
such as the builder's template renderer, are declared per task in `deterministic_options`
and run by the caller, which then reports validation evidence like any other attempt.
"""

import re
import shutil
import subprocess  # noqa: S404  fixed argv, no shell
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import TaskSpec

QUOTED_EDIT = re.compile(
    r"""(?:change|replace|rename|update)\s+(?:the\s+)?(?:text\s+|label\s+|word\s+|title\s+)?["“'`](?P<old>[^"”'`]{1,200})["”'`]\s+"""
    r"""(?:to|with|into)\s+["“'`](?P<new>[^"”'`]{0,200})["”'`]""",
    re.IGNORECASE,
)


@dataclass
class ToolResult:
    ok: bool
    files: dict[str, str] = field(default_factory=dict)  # path -> new content
    output: dict = field(default_factory=dict)
    error: str | None = None


class EngineTool:
    name: str = ""
    description: str = ""
    purposes: tuple[str, ...] = ("generate",)

    def coverage(self, spec: TaskSpec, artifacts: dict[str, str]) -> str | None:
        """Return "exact" or "approximate" when the tool can handle the task, otherwise None."""
        return None

    def run(self, spec: TaskSpec, artifacts: dict[str, str]) -> ToolResult:
        raise NotImplementedError


class TextReplace(EngineTool):
    """Applies an explicit quoted replacement, e.g. change "Sign up" to "Create account"."""

    name = "aaee.text_replace"
    description = "Exact quoted text replacement across the provided files"

    def _match(self, spec: TaskSpec):
        return QUOTED_EDIT.search(spec.task_description)

    def coverage(self, spec, artifacts):
        if spec.task_type not in {"incremental_code_edit", "content_generation", "documentation"} or not artifacts:
            return None
        match = self._match(spec)
        if not match or not any(match.group("old") in content for content in artifacts.values()):
            return None
        return "exact"

    def run(self, spec, artifacts):
        match = self._match(spec)
        if not match:
            return ToolResult(False, error="No quoted replacement found")
        old, new = match.group("old"), match.group("new")
        files = {path: content.replace(old, new) for path, content in artifacts.items() if old in content}
        if not files:
            return ToolResult(False, error=f"Text not found: {old!r}")
        return ToolResult(True, files=files, output={"replaced": old, "with": new, "occurrences": sum(c.count(old) for c in artifacts.values())})


class RuffFormat(EngineTool):
    """Deterministic repair for Python formatting and auto-fixable lint findings."""

    name = "aaee.ruff_format"
    description = "ruff format and ruff check --fix on Python files"
    purposes = ("repair",)

    def coverage(self, spec, artifacts):
        if not shutil.which("ruff") or not any(p.endswith(".py") for p in artifacts):
            return None
        return "approximate"

    def run(self, spec, artifacts):
        ruff = shutil.which("ruff")
        if not ruff:
            return ToolResult(False, error="ruff is not installed")
        with tempfile.TemporaryDirectory(prefix="aaee-ruff-") as tmp:
            root = Path(tmp)
            paths = [p for p in artifacts if p.endswith(".py")]
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(artifacts[path])
            subprocess.run([ruff, "check", "--fix", "--quiet", "--exit-zero", "."], cwd=root, capture_output=True, timeout=60, check=False)  # noqa: S603
            subprocess.run([ruff, "format", "--quiet", "."], cwd=root, capture_output=True, timeout=60, check=False)  # noqa: S603
            files = {p: (root / p).read_text() for p in paths if (root / p).read_text() != artifacts[p]}
        return ToolResult(True, files=files, output={"formatted": sorted(files)})


class TemplateSelect(EngineTool):
    """Picks a starter template from the catalog the caller supplies in `context.templates`."""

    name = "aaee.template_select"
    description = "Keyword match against the caller's template catalog"

    def _scores(self, spec: TaskSpec) -> list[tuple[int, str]]:
        templates = spec.context.get("templates") or []
        words = set(re.findall(r"[a-z]+", spec.task_description.lower()))
        scores = []
        for template in templates:
            if not isinstance(template, dict) or not template.get("id"):
                continue
            keywords = {k.lower() for k in template.get("keywords", [])}
            scores.append((len(words & keywords), str(template["id"])))
        return sorted(scores, reverse=True)

    def coverage(self, spec, artifacts):
        if spec.task_type not in {"application_scaffolding", "architecture_design"}:
            return None
        scores = self._scores(spec)
        if not scores or scores[0][0] == 0:
            return None
        return "exact" if len(scores) == 1 or scores[0][0] > scores[1][0] else "approximate"

    def run(self, spec, artifacts):
        scores = self._scores(spec)
        if not scores:
            return ToolResult(False, error="No template catalog supplied")
        return ToolResult(True, output={"template": scores[0][1], "scores": [{"template": t, "score": s} for s, t in scores[:5]]})


ENGINE_TOOLS: dict[str, EngineTool] = {tool.name: tool for tool in (TextReplace(), RuffFormat(), TemplateSelect())}
