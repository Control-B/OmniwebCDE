"""Bounded escalation driven by verified failures.

The controller classifies each failure, fingerprints it, and decides whether to run a
deterministic repair, fall back to another provider at the same level, move up the ladder
(low-cost GPT-OSS or Grok → hosted standard → hosted advanced), or stop with diagnostics. It stops
on repeated identical failures, unchanged output, exhausted attempts, or exhausted budget.
Escalation is never triggered merely because a stronger model is available.
"""

import hashlib
import re
from dataclasses import dataclass, field

from .contracts import Evidence
from .models import Execution
from .routing_policy import LEVELS

KIND_CATEGORY = {
    "typecheck": "typecheck",
    "lint": "lint",
    "format": "lint",
    "unit_tests": "test_failure",
    "api_tests": "test_failure",
    "integration_tests": "test_failure",
    "e2e": "test_failure",
    "build": "build_failure",
    "mobile_bundle": "build_failure",
    "mobile_config": "build_failure",
    "openapi": "build_failure",
    "migrations": "migration_failure",
    "schema": "migration_failure",
    "response_schema": "schema_invalid",
    "secrets_scan": "security_finding",
    "sast": "security_finding",
    "dependency_scan": "security_finding",
    "dast": "security_finding",
    "path_policy": "security_finding",
    "review": "unknown",
}
PRIORITY = [
    "security_finding",
    "dependency_conflict",
    "migration_failure",
    "build_failure",
    "typecheck",
    "test_failure",
    "lint",
    "schema_invalid",
    "timeout",
    "unknown",
]
DEPENDENCY = re.compile(r"ERESOLVE|could not resolve dependency|version solving failed|ResolutionImpossible|peer dep|conflicting dependencies", re.I)
TIMEOUT = re.compile(r"timed out|timeout|ETIMEDOUT", re.I)
INFRA_ERRORS = {"provider_error", "timeout", "unavailable", "rate_limited"}
NOISE = re.compile(r"(\d+(\.\d+)?(ms|s)\b)|(0x[0-9a-f]+)|([0-9a-f]{12,})|(\d{4}-\d\d-\d\dT[\d:.]+Z?)|(/tmp/[^\s:]+)|(:\d+:\d+)", re.I)


def classify(items: list[Evidence]) -> str:
    found = set()
    for item in items:
        if item.status != "failed":
            continue
        if DEPENDENCY.search(item.output):
            found.add("dependency_conflict")
        elif TIMEOUT.search(item.output) and item.kind in {"build", "e2e", "unit_tests"}:
            found.add("timeout")
        else:
            found.add(KIND_CATEGORY.get(item.kind, "unknown"))
    return next((c for c in PRIORITY if c in found), "unknown")


def fingerprint(items: list[Evidence]) -> str:
    """Stable across runs: durations, addresses, hashes, temp paths, and line positions removed."""
    parts = []
    for item in sorted(items, key=lambda i: (i.kind, i.name)):
        if item.status != "failed":
            continue
        lines = [NOISE.sub("", line).strip() for line in item.output.splitlines() if re.search(r"error|fail|expected|cannot|not found", line, re.I)]
        parts.append(f"{item.kind}:{item.name}:{'|'.join(sorted(set(lines))[:40])}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@dataclass
class Decision:
    action: str  # retry | stop
    reason: str
    category: str
    min_level: int = 0
    purpose: str = "generate"
    exclude_keys: set[str] = field(default_factory=set)
    counts_as_attempt: bool = True


def level_of(execution: Execution) -> int:
    return LEVELS.get((execution.candidate or {}).get("level", ""), 1)


def decide(spec: dict, policy: dict, history: list[Execution], latest: Execution, deterministic_repair: bool) -> Decision:
    escalation = policy["escalation"]
    category = latest.error_category or "unknown"
    key = (latest.candidate or {}).get("key", "")
    exclude = {e.candidate.get("key") for e in history if e.status == "failed" and e.candidate}
    quality = [e for e in history if e.validation == "failed"]
    if category in INFRA_ERRORS:
        recent_infra = 0
        for execution in reversed(history):
            if execution.error_category in INFRA_ERRORS:
                recent_infra += 1
            else:
                break
        if recent_infra >= escalation["provider_fallbacks"]:
            return Decision("stop", f"{recent_infra} provider failures in a row; providers look unavailable", category)
        # Fallback at the same level; an outage is not evidence that a stronger model is needed.
        return Decision(
            "retry",
            f"Provider failure on {key}; trying another model at the same level",
            category,
            min_level=level_of(latest),
            exclude_keys=exclude,
            counts_as_attempt=False,
        )
    if len(quality) >= spec["maximum_attempts"]:
        return Decision("stop", f"Reached the attempt limit ({spec['maximum_attempts']})", category)
    same = [e for e in quality if e.failure_fingerprint and e.failure_fingerprint == latest.failure_fingerprint]
    if len(same) >= escalation["max_identical_failures"]:
        return Decision("stop", f"The same failure repeated {len(same)} times; a stronger attempt is unlikely to differ without new input", category)
    unchanged = [e for e in quality if e.id != latest.id and e.output_hash and e.output_hash == latest.output_hash]
    if unchanged:
        return Decision("stop", "The repair produced the same output as an earlier failed attempt", category)
    if category == "security_finding" and spec["risk_level"] in {"high", "critical"}:
        return Decision("stop", "Security finding on a high-risk task; a person must review it", category)
    if category == "dependency_conflict" and any(e.error_category == "dependency_conflict" for e in quality if e.id != latest.id):
        return Decision("stop", "Dependency conflict persists; resolving it needs a decision about versions", category)
    if category == "lint" and deterministic_repair and latest.strategy != "deterministic":
        return Decision("retry", "Lint or format failure; trying deterministic repair first", category, min_level=0, purpose="repair", exclude_keys=exclude)
    current = level_of(latest)
    next_level = current + 1 if current >= 1 else 1
    return Decision(
        "retry", f"{category.replace('_', ' ')} after {latest.strategy}; escalating", category, min_level=next_level, purpose="repair", exclude_keys=exclude
    )
