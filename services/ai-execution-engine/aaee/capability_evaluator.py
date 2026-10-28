"""Hard eligibility checks for a model against a resolved task.

Only capabilities the gateway registry can actually report are used: structured output,
tool calling, vision, reasoning, prompt caching, and context size. Code quality is not a
registry capability; it is measured by validation and enforced by escalation.
"""

from .contracts import TaskSpec
from .model_registry import ModelView


def evaluate(model: ModelView, spec: TaskSpec, production: bool) -> list[str]:
    """Return the reasons the model is ineligible; an empty list means eligible."""
    reasons = []
    if not model.enabled:
        reasons.append("disabled by an administrator")
    if model.deprecated:
        reasons.append("deprecated")
    if model.family == "development" and production:
        reasons.append("development model is not available in production")
    if spec.allowed_models and model.key not in spec.allowed_models:
        reasons.append("not in the task's allowed models")
    if not model.pricing_known:
        reasons.append("pricing unknown; excluded from automated optimization until an administrator validates it")
    missing = [c for c in spec.required_capabilities if c not in model.capabilities]
    if missing and model.family != "development":
        reasons.append(f"missing capabilities: {', '.join(missing)}")
    if model.context_window is None and model.family != "development":
        reasons.append("context window unknown")
    elif model.context_window is not None and model.context_window < spec.min_context_tokens:
        reasons.append(f"context window {model.context_window} < required {spec.min_context_tokens}")
    return reasons
