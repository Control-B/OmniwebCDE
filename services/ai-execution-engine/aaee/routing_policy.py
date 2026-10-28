"""Versioned routing policies.

A policy holds only configuration: defaults for sparse data, thresholds, and bands. It never
holds model identifiers or prices, which come from the gateway registry and the admin overlay.
Only platform administrators can create or activate policies; user feedback never edits them.
"""

import copy
import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import COMPLEXITIES, TASK_TYPES
from .models import RoutingPolicy

CODE_TASKS = {
    "application_scaffolding", "frontend_generation", "backend_generation", "database_generation",
    "mobile_generation", "incremental_code_edit", "debugging", "test_generation",
}
TEXT_TASKS = {"requirement_analysis", "architecture_design", "documentation", "content_generation"}

# Strategy levels form the escalation ladder. Hosted economy models sit beside GPT-OSS so a
# cheaper hosted model can win on measured cost per success.
LEVELS = {"deterministic": 0, "gpt_oss": 1, "hosted_economy": 1, "hosted_standard": 2, "hosted_advanced": 3, "codex": 4}

DEFAULT_POLICY: dict = {
    # Observations needed before measured success rates replace the conservative defaults.
    "min_samples": 20,
    # Conservative probabilities of an attempt passing validation, used while data is sparse.
    "default_success": {
        "deterministic_exact": {"trivial": 0.95, "simple": 0.9, "normal": 0.85, "complex": 0.7},
        "deterministic_approximate": {"trivial": 0.6, "simple": 0.5, "normal": 0.4, "complex": 0.25},
        "gpt_oss": {"trivial": 0.75, "simple": 0.65, "normal": 0.5, "complex": 0.3},
        "hosted_economy": {"trivial": 0.75, "simple": 0.65, "normal": 0.5, "complex": 0.3},
        "hosted_standard": {"trivial": 0.85, "simple": 0.8, "normal": 0.7, "complex": 0.5},
        "hosted_advanced": {"trivial": 0.9, "simple": 0.88, "normal": 0.8, "complex": 0.68},
        "codex": {"trivial": 0.7, "simple": 0.72, "normal": 0.75, "complex": 0.72},
        "development": {"trivial": 0.5, "simple": 0.5, "normal": 0.5, "complex": 0.5},
    },
    # Required probability that the planned chain of attempts succeeds.
    "quality_threshold": {t: (0.9 if t in {"security_review", "deployment_preparation"} else 0.8) for t in TASK_TYPES},
    # Blended price bands in USD per million tokens ((3 * input + output) / 4).
    "bands": {"economy_max": 1.0, "standard_max": 6.0},
    "gpt_oss_first": True,
    # How much cheaper (measured) another candidate must be before it displaces GPT-OSS.
    "gpt_oss_displacement_margin": 0.15,
    "gpt_oss_excluded_task_types": ["security_review"],
    "gpt_oss_max_risk": "medium",
    # Base complexity and risk per task type; the classifier raises them from evidence.
    "base_complexity": {
        "requirement_analysis": "simple", "architecture_design": "normal", "application_scaffolding": "normal",
        "frontend_generation": "normal", "backend_generation": "normal", "database_generation": "normal",
        "mobile_generation": "normal", "incremental_code_edit": "simple", "debugging": "normal",
        "test_generation": "simple", "security_review": "normal", "deployment_preparation": "normal",
        "documentation": "simple", "content_generation": "trivial",
    },
    "base_risk": {
        "requirement_analysis": "low", "architecture_design": "low", "application_scaffolding": "medium",
        "frontend_generation": "low", "backend_generation": "medium", "database_generation": "medium",
        "mobile_generation": "medium", "incremental_code_edit": "low", "debugging": "medium",
        "test_generation": "low", "security_review": "high", "deployment_preparation": "high",
        "documentation": "low", "content_generation": "low",
    },
    "max_output_tokens": {
        "requirement_analysis": 2_000, "architecture_design": 4_000, "application_scaffolding": 12_000,
        "frontend_generation": 12_000, "backend_generation": 12_000, "database_generation": 6_000,
        "mobile_generation": 12_000, "incremental_code_edit": 6_000, "debugging": 6_000,
        "test_generation": 6_000, "security_review": 4_000, "deployment_preparation": 4_000,
        "documentation": 4_000, "content_generation": 1_500,
    },
    "maximum_attempts": 4,
    "reservation_margin": 1.25,
    # A per-attempt cost added to failed attempts in the expected-cost model (review time, latency).
    "failure_penalty_usd": 0.002,
    "escalation": {
        "max_identical_failures": 2,
        "provider_fallbacks": 3,
        "codex_after_failures": 2,
    },
    "codex": {
        "enabled": True,
        "task_types": sorted(CODE_TASKS - {"database_generation"}),
        "min_complexity": "complex",
        "requires_approval": True,
        "max_duration_seconds": 900,
        "estimated_input_tokens": 150_000,
        "estimated_output_tokens": 15_000,
        "typical_latency_ms": 120_000,
    },
    "human_review_task_types": [],
}

RISK_ORDER = ("low", "medium", "high", "critical")


def validate_config(config: dict) -> dict:
    """Merge onto the default and check value ranges. Unknown keys are rejected."""
    merged = copy.deepcopy(DEFAULT_POLICY)
    for key, value in config.items():
        if key not in DEFAULT_POLICY:
            raise ValueError(f"Unknown policy key: {key}")
        if isinstance(DEFAULT_POLICY[key], dict) and isinstance(value, dict):
            merged[key] = _merge(DEFAULT_POLICY[key], value, key)
        else:
            merged[key] = value
    if not 1 <= int(merged["min_samples"]) <= 10_000:
        raise ValueError("min_samples must be between 1 and 10000")
    if not 1 <= int(merged["maximum_attempts"]) <= 6:
        raise ValueError("maximum_attempts must be between 1 and 6")
    if not 1 <= float(merged["reservation_margin"]) <= 5:
        raise ValueError("reservation_margin must be between 1 and 5")
    for table in merged["default_success"].values():
        for complexity in COMPLEXITIES:
            if not 0 <= float(table[complexity]) <= 1:
                raise ValueError("default_success values must be probabilities")
    for value in merged["quality_threshold"].values():
        if not 0 <= float(value) <= 1:
            raise ValueError("quality_threshold values must be probabilities")
    if merged["gpt_oss_max_risk"] not in RISK_ORDER:
        raise ValueError("gpt_oss_max_risk must be a risk level")
    return merged


def _merge(base: dict, update: dict, path: str) -> dict:
    result = copy.deepcopy(base)
    for key, value in update.items():
        if key not in base:
            raise ValueError(f"Unknown policy key: {path}.{key}")
        result[key] = _merge(base[key], value, f"{path}.{key}") if isinstance(base[key], dict) and isinstance(value, dict) else value
    return result


async def ensure_default(db: AsyncSession) -> RoutingPolicy:
    active = await db.scalar(select(RoutingPolicy).where(RoutingPolicy.status == "active"))
    if active:
        return active
    existing = await db.scalar(select(RoutingPolicy).where(RoutingPolicy.version == 1))
    if existing:
        existing.status = "active"
        await db.flush()
        return existing
    policy = RoutingPolicy(version=1, status="active", traffic_percent=100, config=copy.deepcopy(DEFAULT_POLICY), notes="Built-in default")
    db.add(policy)
    await db.flush()
    return policy


def bucket(task_id: uuid.UUID, salt: int) -> float:
    digest = hashlib.sha256(f"{task_id}:{salt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 * 100


async def policies_for_task(db: AsyncSession, task_id: uuid.UUID) -> tuple[RoutingPolicy, list[RoutingPolicy]]:
    """Return the policy that decides this task and the shadow policies that only observe."""
    active = await ensure_default(db)
    chosen = active
    for experiment in await db.scalars(select(RoutingPolicy).where(RoutingPolicy.status == "experiment").order_by(RoutingPolicy.version)):
        if bucket(task_id, experiment.version) < experiment.traffic_percent:
            chosen = experiment
            break
    shadows = list(await db.scalars(select(RoutingPolicy).where(RoutingPolicy.status == "shadow").order_by(RoutingPolicy.version)))
    if chosen is not active:
        shadows = [active, *shadows]
    return chosen, shadows


def effective(config: dict) -> dict:
    """Policies stored by older versions may lack newer keys; fill them from the default."""
    try:
        return validate_config(config)
    except ValueError:
        return copy.deepcopy(DEFAULT_POLICY)
