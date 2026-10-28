"""Rule-based task classification.

Classification never calls a model: a deterministic pass over the request is cheap and
auditable. When signals conflict the classifier picks the more conservative (higher)
complexity and risk. Clients may raise the complexity with a hint but cannot lower risk.
"""

import re
import uuid

from .contracts import COMPLEXITIES, PHASE_OF_TASK, SENSITIVE_ACTIONS, TaskRequest, TaskSpec
from .routing_policy import RISK_ORDER
from .security import Caller

COMPLEX_WORDS = re.compile(
    r"\b(refactor|migrate|migration|re-?architect|multi[- ]?(file|service|tenant)|across the (codebase|app)|"
    r"concurren\w*|race condition|distributed|real[- ]?time|end[- ]to[- ]end|integrat\w+ with|oauth|sso|"
    r"payments?|stripe|webhooks?|performance|memory leak|deadlock)\b",
    re.IGNORECASE,
)
SIMPLE_WORDS = re.compile(r"\b(rename|typo|copy|text|label|colou?r|spacing|padding|font|title|heading|button text|wording)\b", re.IGNORECASE)
HIGH_RISK_WORDS = re.compile(
    r"\b(auth\w*|password|credential|secret|token|encrypt\w*|permission|rbac|billing|invoice|payment|pci|hipaa|"
    r"gdpr|production|delete (all|every)|drop (table|column|database)|truncate|rm -rf|iam|firewall|ssh key)\b",
    re.IGNORECASE,
)
# Phrases that try to steer the agent away from its instructions. Their presence raises risk;
# it never grants anything.
INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) instructions|disregard (the )?(system|previous)|you are now|"
    r"reveal (the |your )?(system prompt|secrets?|api keys?)|print (the )?(env|environment variables)|"
    r"exfiltrat\w+|curl\s+https?://|base64 -d|BEGIN SYSTEM PROMPT)",
    re.IGNORECASE,
)
SENSITIVE_TEXT = {
    "destructive_database_change": re.compile(r"\b(drop (table|column|database)|truncate|delete (all|every) (rows|records|users))\b", re.I),
    "production_deploy": re.compile(r"\b(deploy|release|ship|promote) (it |this |the app )?to production\b", re.I),
    "production_credential_change": re.compile(r"\b(rotate|change|replace|update) (the )?(production )?(api key|secret|credential|password)s?\b", re.I),
    "billing_logic_change": re.compile(r"\b(change|modify|update) (the )?(billing|pricing|invoice|subscription) (logic|rules|calculation)\b", re.I),
    "cloud_resource_change": re.compile(r"\b(create|delete|resize|destroy) (a |the )?(droplet|vm|server|bucket|database cluster|load balancer)\b", re.I),
}


def _raise(current: str, candidate: str, order: tuple[str, ...]) -> str:
    return candidate if order.index(candidate) > order.index(current) else current


def estimate_tokens(text: str) -> int:
    return int(len(text) / 3.5) + 1


def classify(request: TaskRequest, identity: Caller, policy: dict, task_id: uuid.UUID, settings_budget_usd: float) -> TaskSpec:
    text = request.task_description
    artifact_chars = sum(len(a.content or "") for a in request.input_artifacts)
    prompt_chars = len(request.prompt.system + request.prompt.user) if request.prompt else 0
    context_tokens = estimate_tokens("x" * (artifact_chars + prompt_chars + len(text)))

    complexity = policy["base_complexity"][request.task_type]
    reasons: list[str] = []
    if COMPLEX_WORDS.search(text):
        complexity = _raise(complexity, "complex", COMPLEXITIES)
    elif SIMPLE_WORDS.search(text) and len(text) < 240 and len(request.input_artifacts) <= 2 and complexity == "simple":
        complexity = "trivial"
    if len(request.input_artifacts) > 25 or context_tokens > 60_000:
        complexity = _raise(complexity, "complex", COMPLEXITIES)
    elif len(request.input_artifacts) > 8 or context_tokens > 16_000:
        complexity = _raise(complexity, "normal", COMPLEXITIES)
    if request.complexity:
        complexity = _raise(complexity, request.complexity, COMPLEXITIES)

    risk = policy["base_risk"][request.task_type]
    if HIGH_RISK_WORDS.search(text):
        risk = _raise(risk, "high", RISK_ORDER)
        reasons.append("Touches authentication, credentials, billing, production, or destructive operations")
    scanned = text + "\n" + "\n".join((a.content or "")[:20_000] for a in request.input_artifacts)
    if request.prompt:
        scanned += "\n" + request.prompt.user[:20_000]
    if INJECTION.search(scanned):
        risk = _raise(risk, "high", RISK_ORDER)
        reasons.append("Input contains instruction-override or exfiltration phrases; treated as untrusted")

    actions = set(request.permitted_actions)
    approvals = []
    for action, pattern in SENSITIVE_TEXT.items():
        if pattern.search(text):
            actions.add(action)
    for action in sorted(actions & SENSITIVE_ACTIONS):
        approvals.append(f"sensitive_action:{action}")
        risk = "critical"
        reasons.append(f"Requires {action.replace('_', ' ')}")
    if request.execution_environment.kind == "authorized_test_environment":
        risk = _raise(risk, "high", RISK_ORDER)
        reasons.append("Runs against a test environment; dynamic scans need an authorized target")
    if request.task_type in policy.get("human_review_task_types", []):
        approvals.append("human_review")

    capabilities = sorted(set(request.required_capabilities))
    max_output = (request.prompt.max_output_tokens if request.prompt and request.prompt.max_output_tokens else None) or policy[
        "max_output_tokens"
    ][request.task_type]
    budget = min(request.maximum_budget_usd or settings_budget_usd, 1_000)
    environment = request.execution_environment.model_dump()
    if request.workspace_id and not environment.get("workspace_id"):
        environment["workspace_id"] = request.workspace_id

    return TaskSpec(
        task_id=task_id,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        project_id=request.project_id or identity.project_id,
        workspace_id=request.workspace_id,
        task_type=request.task_type,
        task_description=text,
        input_artifact_references=[{"path": a.path, "chars": len(a.content or ""), "artifact_id": str(a.artifact_id) if a.artifact_id else None}
                                   for a in request.input_artifacts],
        required_capabilities=capabilities,
        min_context_tokens=context_tokens + max_output,
        complexity=complexity,
        development_phase=request.development_phase or PHASE_OF_TASK[request.task_type],
        risk_level=risk,
        risk_reasons=reasons,
        quality_threshold=max(request.quality_threshold or 0, policy["quality_threshold"][request.task_type]),
        latency_target_ms=request.latency_target_ms,
        maximum_budget_usd=budget,
        maximum_attempts=min(request.maximum_attempts or policy["maximum_attempts"], policy["maximum_attempts"], 6),
        allowed_models=request.allowed_models,
        allowed_tools=request.allowed_tools,
        permitted_actions=sorted(actions),
        allowed_paths=request.allowed_paths,
        execution_environment=environment,
        approval_requirements=approvals,
        deterministic_options=[o.model_dump() for o in request.deterministic_options],
        prompt=request.prompt.model_dump() if request.prompt else None,
        context=request.context,
        caller_role=identity.role,
        classification_source="rules",
    )
