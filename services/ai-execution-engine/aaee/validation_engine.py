"""Acceptance criteria per task type and the checks AAEE runs itself.

Passing these checks is evidence, not proof: compiling code does not establish functional
correctness, and scanners or model reviews do not establish regulatory compliance. Required
checks that were not run, or could not run, count as not passed.
"""

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess  # noqa: S404  fixed argv, no shell
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import jsonschema

from .config import Settings
from .contracts import Evidence, TaskSpec
from .security import find_secrets

DISCLAIMER = (
    "Checks passing is evidence, not proof of functional correctness. Security scanners and model reviews do not establish "
    "regulatory compliance."
)

# Each entry is a list of alternatives; one of the kinds in each group must pass.
CRITERIA: dict[str, list[list[str]]] = {
    "requirement_analysis": [["response_schema"]],
    "architecture_design": [["response_schema"]],
    "application_scaffolding": [["typecheck", "build"], ["build", "api_tests", "unit_tests"]],
    "frontend_generation": [["typecheck"], ["build"]],
    "backend_generation": [["api_tests", "unit_tests", "integration_tests"]],
    "database_generation": [["migrations"], ["schema", "api_tests"]],
    "mobile_generation": [["mobile_config"], ["mobile_bundle"]],
    "incremental_code_edit": [["typecheck", "unit_tests", "build", "api_tests", "lint", "format", "review"]],
    "debugging": [["unit_tests", "api_tests", "integration_tests", "build", "e2e"]],
    "test_generation": [["unit_tests", "api_tests", "integration_tests", "e2e"]],
    "security_review": [["secrets_scan"], ["sast", "dependency_scan"], ["review"]],
    "deployment_preparation": [["build"], ["secrets_scan"]],
    "documentation": [["response_schema", "review", "format"]],
    "content_generation": [["response_schema", "review", "format"]],
}
CODE_OUTPUT_TASKS = {
    "application_scaffolding", "frontend_generation", "backend_generation", "database_generation", "mobile_generation",
    "incremental_code_edit", "debugging", "test_generation", "deployment_preparation",
}
# Mandatory gates that apply whatever strategy produced the output.
MANDATORY = {task: (["secrets_scan", "path_policy"] if task in CODE_OUTPUT_TASKS else []) for task in CRITERIA}
DENIED_PATHS = [".git/*", ".github/*", ".gitlab-ci.yml", ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "**/secrets/*",
                "*/.env", "*/.env.*"]


@dataclass
class Verdict:
    passed: bool
    missing: list[str] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    summary: str = ""


def required_checks(spec: TaskSpec) -> dict:
    return {"groups": CRITERIA[spec.task_type], "mandatory": MANDATORY[spec.task_type], "disclaimer": DISCLAIMER}


def evaluate(spec: TaskSpec, items: list[Evidence]) -> Verdict:
    by_kind: dict[str, list[Evidence]] = {}
    for item in items:
        by_kind.setdefault(item.kind, []).append(item)
    failing = [f"{i.name} ({i.kind})" for i in items if i.status == "failed"]
    missing = []
    for group in CRITERIA[spec.task_type]:
        if not any(any(e.status == "passed" for e in by_kind.get(kind, [])) for kind in group):
            missing.append(" or ".join(group))
    for kind in MANDATORY[spec.task_type]:
        if not any(e.status == "passed" for e in by_kind.get(kind, [])):
            missing.append(f"{kind} (mandatory)")
    passed = not failing and not missing
    parts = []
    if failing:
        parts.append("Failed: " + ", ".join(failing))
    if missing:
        parts.append("Not passed or not run: " + ", ".join(missing))
    return Verdict(passed, missing, failing, "; ".join(parts) or "All required checks passed")


def digest(items: list[Evidence]) -> str:
    return hashlib.sha256(json.dumps([i.model_dump() for i in items], sort_keys=True).encode()).hexdigest()


def safe_relative(path: str) -> bool:
    pure = PurePosixPath(path)
    return bool(path.strip()) and not pure.is_absolute() and ".." not in pure.parts and "\\" not in path and "\x00" not in path


def path_allowed(path: str, allowed: list[str]) -> str | None:
    pure = PurePosixPath(path)
    if not safe_relative(path):
        return "path escapes the workspace"
    for pattern in DENIED_PATHS:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(pure.name, pattern):
            return f"path is protected ({pattern})"
    if allowed and not any(path == a or path.startswith(a.rstrip("/") + "/") or fnmatch.fnmatch(path, a) for a in allowed):
        return "path is outside the task's allowed paths"
    return None


def check_paths(spec: TaskSpec, files: dict[str, str] | list[str]) -> Evidence:
    paths = list(files)
    problems = [{"path": p, "problem": reason} for p in paths if (reason := path_allowed(p, spec.allowed_paths))]
    return Evidence(name="engine.path_policy", kind="path_policy", status="failed" if problems else "passed", findings=problems[:100],
                    output=f"{len(paths)} file(s) checked")


def check_response_schema(spec: TaskSpec, content: str) -> Evidence:
    prompt = spec.prompt or {}
    if prompt.get("response_format") != "json":
        status = "passed" if content.strip() else "failed"
        return Evidence(name="engine.response", kind="response_schema", status=status, output="" if content.strip() else "Empty response")
    try:
        value = parse_json(content)
    except ValueError as exc:
        return Evidence(name="engine.response", kind="response_schema", status="failed", output=f"Invalid JSON: {exc}"[:500])
    schema = prompt.get("json_schema")
    if schema:
        try:
            jsonschema.validate(value, schema)
        except jsonschema.ValidationError as exc:
            return Evidence(name="engine.response", kind="response_schema", status="failed", output=f"Schema: {exc.message}"[:500])
        except jsonschema.SchemaError as exc:
            return Evidence(name="engine.response", kind="response_schema", status="unavailable", output=f"Invalid schema: {exc.message}"[:300])
    return Evidence(name="engine.response", kind="response_schema", status="passed")


def parse_json(content: str):
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc
        raise ValueError("no JSON object found") from None


def scan_secrets(files: dict[str, str], settings: Settings) -> Evidence:
    """gitleaks when installed; otherwise AAEE's built-in patterns, labelled as such."""
    gitleaks = shutil.which("gitleaks") or shutil.which("gitleaks", path=settings.scanner_path)
    if gitleaks and files:
        with tempfile.TemporaryDirectory(prefix="aaee-scan-") as tmp:
            root = Path(tmp) / "src"
            for path, content in files.items():
                if not safe_relative(path):
                    continue
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            report = Path(tmp) / "report.json"
            result = subprocess.run(  # noqa: S603
                [gitleaks, "dir", str(root), "--no-banner", "--report-format", "json", "--report-path", str(report), "--exit-code", "3"],
                capture_output=True, timeout=120, check=False, env={"PATH": os.environ.get("PATH", "")},
            )
            if result.returncode in (0, 3):
                findings = json.loads(report.read_text() or "[]") if report.exists() else []
                safe = [{"rule": f.get("RuleID"), "file": f.get("File", "").replace(str(root) + "/", ""), "line": f.get("StartLine")}
                        for f in findings][:100]
                return Evidence(name="engine.gitleaks", kind="secrets_scan", status="failed" if safe else "passed", findings=safe,
                                output=f"gitleaks: {len(safe)} finding(s)")
    findings = [{"file": path, "match": hit} for path, content in files.items() for hit in find_secrets(content)][:100]
    return Evidence(name="engine.secret_patterns", kind="secrets_scan", status="failed" if findings else "passed", findings=findings,
                    output=f"built-in patterns (gitleaks not installed): {len(findings)} finding(s)" if not gitleaks else f"{len(findings)} finding(s)")


def engine_checks(spec: TaskSpec, settings: Settings, content: str | None, files: dict[str, str] | None) -> list[Evidence]:
    items = []
    if content is not None and not files:
        items.append(check_response_schema(spec, content))
    if files is not None:
        items.append(check_paths(spec, files))
        items.append(scan_secrets(files, settings))
    return items
