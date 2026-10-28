from dataclasses import dataclass, field

from .config import Settings
from .models import ModelEntry
from .providers import DEV_PROVIDER, PROVIDERS

TIERS = ("economy", "standard", "advanced", "self_hosted")
COMPLEXITY_TIER = {"simple": "economy", "normal": "standard", "complex": "advanced"}
DEFAULT_CONTEXT = 8_192


@dataclass
class RouteRequest:
    tier: str
    capabilities: list[str] = field(default_factory=list)
    estimated_input_tokens: int = 0
    max_output_tokens: int = 1024
    allowed_providers: list[str] = field(default_factory=list)
    pinned_model: str | None = None  # "provider/model_id"
    remaining_budget_usd: float | None = None


def blended_price(entry: ModelEntry) -> float | None:
    if entry.input_usd_per_mtok is None or entry.output_usd_per_mtok is None:
        return None
    return (entry.input_usd_per_mtok + entry.output_usd_per_mtok) / 2


def worst_case_cost(entry: ModelEntry, input_tokens: int, output_tokens: int) -> float:
    return ((entry.input_usd_per_mtok or 0) * input_tokens + (entry.output_usd_per_mtok or 0) * output_tokens) / 1_000_000


def in_tier(entry: ModelEntry, tier: str, settings: Settings) -> bool:
    kind = "development" if entry.provider == DEV_PROVIDER else PROVIDERS[entry.provider].kind
    if tier == "self_hosted":
        return kind == "self_hosted"
    if kind == "self_hosted":
        return False
    price = blended_price(entry)
    if price is None:
        return False
    if tier == "economy":
        return price <= settings.economy_max_blended_usd
    if tier == "standard":
        return price <= settings.standard_max_blended_usd
    return True


def _order(tier: str, entries: list[ModelEntry]) -> list[ModelEntry]:
    # Economy prefers the cheapest model; higher tiers prefer the most capable model inside the
    # tier's price ceiling, using price and context window as capability proxies.
    if tier == "economy":
        return sorted(entries, key=lambda e: (blended_price(e) or 0, -(e.context_window or 0)))
    return sorted(entries, key=lambda e: (-(blended_price(e) or 0), -(e.context_window or 0)))


def candidates(entries: list[ModelEntry], request: RouteRequest, settings: Settings) -> list[ModelEntry]:
    usable = [
        e
        for e in entries
        if e.available
        and e.routable
        and not e.deprecated
        and (not request.allowed_providers or e.provider in request.allowed_providers or e.provider == DEV_PROVIDER)
        and all(cap in e.capabilities for cap in request.capabilities)
        and (e.context_window or DEFAULT_CONTEXT) >= request.estimated_input_tokens + request.max_output_tokens
        and (
            request.remaining_budget_usd is None
            or worst_case_cost(e, request.estimated_input_tokens, request.max_output_tokens) <= request.remaining_budget_usd
        )
    ]
    real = [e for e in usable if e.provider != DEV_PROVIDER]
    dev = [e for e in usable if e.provider == DEV_PROVIDER]
    ordered = _order(request.tier, [e for e in real if in_tier(e, request.tier, settings)])
    if request.pinned_model:
        pinned = [e for e in real if f"{e.provider}/{e.model_id}" == request.pinned_model]
        ordered = pinned + [e for e in ordered if e not in pinned]
    # The development model is a last resort and only exists outside production.
    return ordered if real else dev


def escalation_path(start: str, max_escalations: int) -> list[str]:
    if start == "self_hosted":
        return ["self_hosted"]
    ladder = ["economy", "standard", "advanced"]
    index = ladder.index(start)
    return ladder[index : index + 1 + max(0, max_escalations)]
