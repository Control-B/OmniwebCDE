"""Cost-aware execution planning.

The planner minimises the expected cost of a *successful* task. For each eligible first
attempt it builds the escalation chain that would follow a failure and computes

    E[cost] = c1 + (1 - p1) * (c2 + (1 - p2) * (...))      P[success] = 1 - prod(1 - pi)

then ranks chains by E[cost] / P[success], subject to capability, pricing, context, budget,
latency, security, and quality constraints. Success probabilities are measured outcomes when
there are at least `min_samples` observations (using a Wilson lower bound), otherwise the
active policy's conservative defaults. Mandatory gates are applied independently of the
chosen strategy, so a cheaper route can never skip approvals or security checks.
"""

from dataclasses import dataclass, field
from typing import Protocol

from .capability_evaluator import evaluate
from .contracts import PHASE_OF_TASK, TaskSpec
from .deterministic_tools import ENGINE_TOOLS
from .model_registry import ModelView
from .routing_policy import LEVELS, RISK_ORDER
from .task_classifier import estimate_tokens
from .validation_engine import required_checks

EXPECTED_OUTPUT_FRACTION = 0.5


@dataclass
class Observation:
    samples: int
    successes: int
    lower_bound: float
    mean_cost_usd: float
    p50_latency_ms: int | None


class Stats(Protocol):
    def lookup(self, level: str, key: str, task_type: str, complexity: str) -> Observation | None: ...


class NoStats:
    def lookup(self, level, key, task_type, complexity):
        return None


@dataclass
class Candidate:
    strategy: str  # deterministic | low_cost_model | hosted_model | human_approval
    level_name: str
    model: ModelView | None = None
    tool: str | None = None
    tool_runner: str = "engine"  # engine | caller
    coverage: str | None = None
    est_input_tokens: int = 0
    est_output_tokens: int = 0
    max_output_tokens: int = 0
    expected_cost_usd: float = 0.0
    worst_case_usd: float = 0.0
    p_success: float = 0.0
    p_source: str = "default"
    samples: int = 0
    latency_ms: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def level(self) -> int:
        return LEVELS.get(self.level_name, LEVELS["hosted_standard"]) if self.level_name != "development" else 1

    @property
    def key(self) -> str:
        if self.strategy == "deterministic":
            return f"tool:{self.tool}"
        return self.model.key if self.model else self.strategy

    def view(self) -> dict:
        return {
            "key": self.key, "strategy": self.strategy, "level": self.level_name, "tool": self.tool, "tool_runner": self.tool_runner,
            "coverage": self.coverage, "provider": self.model.provider if self.model else None,
            "model_id": self.model.model_id if self.model else None, "model_family": self.model.family if self.model else None,
            "hosting_mode": self.model.hosting_mode if self.model else None, "billing_model": self.model.billing_model if self.model else "none",
            "estimated_input_tokens": self.est_input_tokens, "estimated_output_tokens": self.est_output_tokens,
            "max_output_tokens": self.max_output_tokens, "expected_cost_usd": round(self.expected_cost_usd, 6),
            "worst_case_usd": round(self.worst_case_usd, 6), "p_success": round(self.p_success, 4), "p_source": self.p_source,
            "samples": self.samples, "latency_ms": self.latency_ms, "notes": self.notes,
        }


@dataclass
class PlanContext:
    budget_available_usd: float
    execution_ceiling_usd: float
    attempts_used: int = 0
    quality_failures: int = 0
    min_level: int = 0
    exclude_keys: set[str] = field(default_factory=set)
    purpose: str = "generate"
    production: bool = False
    approved_keys: set[str] = field(default_factory=set)
    overage_approved: bool = False


def phase_rules(spec: TaskSpec, policy: dict) -> dict:
    """Rules of the requested phase, never looser than the task type's own phase minimum."""
    requested = policy["phases"][spec.development_phase]
    inherent = policy["phases"][PHASE_OF_TASK[spec.task_type]]
    min_level = max(requested["min_level"], inherent["min_level"])
    return {**requested, "min_level": min_level, "max_level": max(requested["max_level"], min_level)}


def level_of_model(model: ModelView, policy: dict) -> str:
    if model.family == "development":
        return "development"
    blended = model.blended_usd_per_mtok or 0
    if model.family in policy["low_cost_families"] and blended <= policy["low_cost_max_blended_usd"]:
        return "low_cost"
    return band(model, policy)


def band(model: ModelView, policy: dict) -> str:
    blended = model.blended_usd_per_mtok or 0
    if blended <= policy["bands"]["economy_max"]:
        return "hosted_economy"
    if blended <= policy["bands"]["standard_max"]:
        return "hosted_standard"
    return "hosted_advanced"


def _probability(candidate: Candidate, spec: TaskSpec, policy: dict, stats: Stats, default_table: str) -> None:
    observed = stats.lookup(candidate.level_name, candidate.key, spec.task_type, spec.complexity)
    if observed and observed.samples >= policy["min_samples"]:
        candidate.p_success = observed.lower_bound
        candidate.p_source = "observed"
        candidate.samples = observed.samples
        candidate.latency_ms = observed.p50_latency_ms
        return
    candidate.p_success = float(policy["default_success"][default_table][spec.complexity])
    candidate.p_source = "default"
    candidate.samples = observed.samples if observed else 0


def build_candidates(spec: TaskSpec, models: list[ModelView], policy: dict, stats: Stats, ctx: PlanContext,
                     artifacts: dict[str, str]) -> tuple[list[Candidate], list[dict]]:
    excluded: list[dict] = []
    candidates: list[Candidate] = []
    prompt_text = ((spec.prompt or {}).get("system", "") + (spec.prompt or {}).get("user", "")) or spec.task_description
    max_output = (spec.prompt or {}).get("max_output_tokens") or policy["max_output_tokens"][spec.task_type]
    est_input = max(estimate_tokens(prompt_text) + sum(estimate_tokens(c) for c in artifacts.values()), spec.min_context_tokens - max_output)
    est_output = int(max_output * EXPECTED_OUTPUT_FRACTION)
    margin = policy["reservation_margin"]

    # Strategy A: deterministic tools.
    allowed_tools = set(spec.allowed_tools)
    for name, tool in ENGINE_TOOLS.items():
        if ctx.purpose not in tool.purposes or (allowed_tools and name not in allowed_tools):
            continue
        coverage = tool.coverage(spec, artifacts)
        if coverage:
            candidate = Candidate("deterministic", "deterministic", tool=name, tool_runner="engine", coverage=coverage)
            _probability(candidate, spec, policy, stats, f"deterministic_{coverage}")
            candidates.append(candidate)
    if ctx.purpose == "generate":
        for option in spec.deterministic_options:
            if allowed_tools and option["tool"] not in allowed_tools:
                continue
            candidate = Candidate("deterministic", "deterministic", tool=option["tool"], tool_runner="caller", coverage=option["coverage"])
            _probability(candidate, spec, policy, stats, f"deterministic_{option['coverage']}")
            candidates.append(candidate)

    # Strategies B and C: low-cost models (GPT-OSS, economical Grok) and hosted models, all
    # called through the gateway. The development phase bounds which levels and providers apply.
    phase = phase_rules(spec, policy)
    low_cost_blocked = None
    if spec.task_type in policy["low_cost_excluded_task_types"]:
        low_cost_blocked = "low-cost models are excluded for this task type by policy"
    elif RISK_ORDER.index(spec.risk_level) > RISK_ORDER.index(policy["low_cost_max_risk"]):
        low_cost_blocked = f"risk {spec.risk_level} exceeds the policy's low-cost limit ({policy['low_cost_max_risk']})"
    preferred = [m for m in models if m.key in phase["preferred_models"] and not evaluate(m, spec, ctx.production)]
    real_models = [m for m in models if m.family != "development"]
    for model in models:
        reasons = evaluate(model, spec, ctx.production)
        level = level_of_model(model, policy)
        if model.family == "development":
            if any(not evaluate(m, spec, ctx.production) for m in real_models):
                reasons.append("a real model is available")
        else:
            if level == "low_cost" and low_cost_blocked:
                reasons.append(low_cost_blocked)
            if phase["providers"] and model.provider not in phase["providers"]:
                reasons.append(f"provider not allowed in the {spec.development_phase} phase")
            if preferred and model not in preferred:
                reasons.append(f"the {spec.development_phase} phase prefers other models")
            if not phase["min_level"] <= LEVELS[level] <= phase["max_level"]:
                reasons.append(f"{level.replace('_', ' ')} is outside the {spec.development_phase} phase's levels "
                               f"{phase['min_level']}-{phase['max_level']}")
        if reasons:
            excluded.append({"key": model.key, "reasons": reasons})
            continue
        output_cap = min(max_output, model.max_output_tokens or max_output)
        candidate = Candidate(
            "low_cost_model" if level == "low_cost" else "hosted_model", level, model=model,
            est_input_tokens=est_input, est_output_tokens=min(est_output, output_cap), max_output_tokens=output_cap,
        )
        candidate.expected_cost_usd = model.cost(est_input, candidate.est_output_tokens)
        candidate.worst_case_usd = model.cost(int(est_input * margin), output_cap)
        _probability(candidate, spec, policy, stats, level)
        if model.family == "development":
            candidate.notes.append("Development model: placeholder output, non-production only")
        if model in preferred:
            candidate.notes.append(f"Preferred for the {spec.development_phase} phase")
        candidates.append(candidate)

    filtered = []
    limit = min(ctx.budget_available_usd, ctx.execution_ceiling_usd)
    for candidate in candidates:
        reasons = []
        if candidate.key in ctx.exclude_keys:
            reasons.append("already failed for this task")
        if candidate.level < ctx.min_level and candidate.strategy != "deterministic":
            reasons.append("below the escalation level required by earlier failures")
        if candidate.strategy == "deterministic" and ctx.min_level > 0:
            reasons.append("deterministic handling already failed or does not address this failure")
        if candidate.worst_case_usd > limit + 1e-12:
            reasons.append(f"worst-case ${candidate.worst_case_usd:.4f} exceeds available ${limit:.4f}")
        if spec.latency_target_ms and candidate.latency_ms and candidate.latency_ms > spec.latency_target_ms:
            reasons.append(f"latency {candidate.latency_ms} ms exceeds target {spec.latency_target_ms} ms")
        if reasons:
            excluded.append({"key": candidate.key, "reasons": reasons, "worst_case_usd": round(candidate.worst_case_usd, 6)})
        else:
            filtered.append(candidate)
    return filtered, excluded


def chain_for(first: Candidate, candidates: list[Candidate], attempts_left: int) -> list[Candidate]:
    chain = [first]
    for level in sorted({c.level for c in candidates if c.level > first.level}):
        if len(chain) >= attempts_left:
            break
        options = [c for c in candidates if c.level == level and c.strategy != "deterministic"]
        if options:
            chain.append(min(options, key=lambda c: c.expected_cost_usd / max(c.p_success, 1e-6)))
    return chain


def chain_economics(chain: list[Candidate], penalty: float) -> tuple[float, float]:
    expected, reach = 0.0, 1.0
    for candidate in chain:
        expected += reach * (candidate.expected_cost_usd + (1 - candidate.p_success) * penalty)
        reach *= 1 - candidate.p_success
    return expected, 1 - reach


def plan(spec: TaskSpec, models: list[ModelView], policy: dict, stats: Stats, ctx: PlanContext,
         artifacts: dict[str, str] | None = None) -> dict:
    artifacts = artifacts or {}
    candidates, excluded = build_candidates(spec, models, policy, stats, ctx, artifacts)
    attempts_left = max(1, spec.maximum_attempts - ctx.attempts_used)
    ranked = []
    for candidate in candidates:
        chain = chain_for(candidate, candidates, attempts_left)
        expected, p_chain = chain_economics(chain, policy["failure_penalty_usd"])
        ranked.append({
            "candidate": candidate, "chain": chain, "expected_cost_usd": expected, "p_chain": p_chain,
            "score": expected / max(p_chain, 1e-6), "viable": p_chain >= spec.quality_threshold,
        })
    ranked.sort(key=lambda r: (not r["viable"], r["score"], -r["p_chain"], -(r["candidate"].model.priority if r["candidate"].model else 0)))
    warnings: list[str] = []
    chosen = ranked[0] if ranked else None
    if chosen and not chosen["viable"]:
        chosen = max(ranked, key=lambda r: (r["p_chain"], -r["score"]))
        warnings.append(f"No plan reaches the quality threshold {spec.quality_threshold:.2f}; using the most reliable chain "
                        f"(estimated {chosen['p_chain']:.2f})")
    if chosen and policy["low_cost_first"] and chosen["candidate"].strategy not in {"deterministic", "low_cost_model"}:
        cheap = next((r for r in ranked if r["viable"] and r["candidate"].strategy == "low_cost_model"), None)
        rival = chosen["candidate"]
        if cheap and not (rival.p_source == "observed" and chosen["score"] < cheap["score"] * (1 - policy["low_cost_displacement_margin"])):
            chosen = cheap
            warnings.append("Low-cost first: no measured evidence that another model is cheaper per successful task")
    if chosen and ctx.purpose == "generate" and chosen["candidate"].strategy != "deterministic":
        deterministic = next((r for r in ranked if r["candidate"].strategy == "deterministic" and r["viable"]), None)
        if deterministic:
            chosen = deterministic

    approvals = list(spec.approval_requirements)
    budget_blocked = [e for e in excluded if any("exceeds available" in r for r in e.get("reasons", []))]
    if chosen:
        candidate = chosen["candidate"]
        if candidate.notes and any("Development model" in n for n in candidate.notes):
            warnings.append("Only the development model is available: output is a placeholder, not AI-generated")
    elif budget_blocked and not ctx.overage_approved:
        approvals.append("budget_overage")
    gates = {"approvals": sorted(set(approvals)), **required_checks(spec)}
    result = {
        "policy": {"min_samples": policy["min_samples"], "quality_threshold": spec.quality_threshold},
        "chosen": chosen["candidate"].view() if chosen else {"strategy": "human_approval", "key": "human", "level": "human"},
        "chain": [c.view() for c in chosen["chain"]] if chosen else [],
        "estimated_cost_usd": round(chosen["expected_cost_usd"], 6) if chosen else 0.0,
        "p_chain": round(chosen["p_chain"], 4) if chosen else 0.0,
        "reservation_usd": round(chosen["candidate"].worst_case_usd, 6) if chosen else 0.0,
        "ranked": [
            {**r["candidate"].view(), "chain_expected_cost_usd": round(r["expected_cost_usd"], 6), "p_chain": round(r["p_chain"], 4),
             "cost_per_success_usd": round(r["score"], 6), "viable": r["viable"]}
            for r in ranked[:12]
        ],
        "excluded": excluded[:40],
        "gates": gates,
        "warnings": warnings,
        "budget_available_usd": round(min(ctx.budget_available_usd, ctx.execution_ceiling_usd), 6),
    }
    if not chosen:
        result["warnings"].append("No automated strategy is eligible; a person must handle or approve this task")
    return result


def candidate_from_view(view: dict, models: list[ModelView]) -> Candidate | None:
    """Rebuild the chosen candidate when executing a stored plan."""
    if view.get("strategy") == "deterministic":
        return Candidate("deterministic", "deterministic", tool=view["tool"], tool_runner=view["tool_runner"], coverage=view.get("coverage"),
                         p_success=view["p_success"])
    model = next((m for m in models if m.provider == view.get("provider") and m.model_id == view.get("model_id")), None)
    if not model:
        return None
    return Candidate(view["strategy"], view["level"], model=model, est_input_tokens=view["estimated_input_tokens"],
                     est_output_tokens=view["estimated_output_tokens"], max_output_tokens=view["max_output_tokens"],
                     expected_cost_usd=view["expected_cost_usd"], worst_case_usd=view["worst_case_usd"], p_success=view["p_success"],
                     p_source=view["p_source"])
