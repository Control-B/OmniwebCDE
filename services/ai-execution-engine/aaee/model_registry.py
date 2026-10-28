"""Model registry view: the gateway's discovered models plus AAEE's administrative overlay.

Model identifiers, context windows, and prices are never invented here. They come from the
gateway (provider list-models APIs and LiteLLM's cost map) or from an administrator. Models
whose pricing cannot be established are marked `unknown` and excluded from automated cost
optimization until an administrator supplies validated prices.
"""

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .inference_gateway import Gateway
from .models import ModelPolicy
from .security import Caller

HOSTING = {
    "openai": "first_party_api", "anthropic": "first_party_api", "gemini": "first_party_api",
    "openrouter": "inference_provider", "openai_compatible": "self_hosted", "ollama": "self_hosted",
    "omniweb_dev": "development",
}
KNOWN_PRICING_SOURCES = {"provider", "litellm"}


@dataclass
class ModelView:
    provider: str
    model_id: str
    display_name: str
    family: str  # gpt_oss | hosted | development
    hosting_mode: str
    capabilities: set[str]
    context_window: int | None
    max_output_tokens: int | None
    input_usd_per_mtok: float | None
    output_usd_per_mtok: float | None
    cached_usd_per_mtok: float | None
    infra_usd_per_mtok: float
    pricing_status: str  # catalog | admin_validated | development | unknown
    pricing_source: str
    billing_model: str  # platform | customer
    enabled: bool = True
    priority: int = 0
    rate_limit_rpm: int | None = None
    deprecated: bool = False
    api: str = "chat"
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model_id}"

    @property
    def pricing_known(self) -> bool:
        return self.pricing_status != "unknown"

    @property
    def blended_usd_per_mtok(self) -> float | None:
        if self.input_usd_per_mtok is None or self.output_usd_per_mtok is None:
            return None
        return (3 * self.input_usd_per_mtok + self.output_usd_per_mtok) / 4 + self.infra_usd_per_mtok

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        if not self.pricing_known:
            raise ValueError(f"Pricing for {self.key} is unknown")
        cached_price = self.cached_usd_per_mtok if self.cached_usd_per_mtok is not None else self.input_usd_per_mtok
        uncached = max(0, input_tokens - cached_tokens)
        return (
            uncached * (self.input_usd_per_mtok or 0)
            + cached_tokens * (cached_price or 0)
            + output_tokens * (self.output_usd_per_mtok or 0)
            + (input_tokens + output_tokens) * self.infra_usd_per_mtok
        ) / 1_000_000

    def view(self) -> dict:
        return {
            "key": self.key, "provider": self.provider, "model_id": self.model_id, "display_name": self.display_name,
            "family": self.family, "hosting_mode": self.hosting_mode, "capabilities": sorted(self.capabilities),
            "context_window": self.context_window, "max_output_tokens": self.max_output_tokens,
            "input_usd_per_mtok": self.input_usd_per_mtok, "output_usd_per_mtok": self.output_usd_per_mtok,
            "cached_usd_per_mtok": self.cached_usd_per_mtok, "infra_usd_per_mtok": self.infra_usd_per_mtok,
            "pricing_status": self.pricing_status, "pricing_source": self.pricing_source, "billing_model": self.billing_model,
            "enabled": self.enabled, "priority": self.priority, "rate_limit_rpm": self.rate_limit_rpm, "deprecated": self.deprecated,
            "api": self.api, "notes": self.notes,
        }


def family_of(provider: str, model_id: str) -> str:
    if provider == "omniweb_dev":
        return "development"
    if "gpt-oss" in model_id.lower():
        return "gpt_oss"
    return "hosted"


def build_view(entry: dict, overlays: list[ModelPolicy]) -> ModelView:
    provider, model_id = entry["provider"], entry["model_id"]
    hosting = HOSTING.get(provider, "inference_provider")
    capabilities = set(entry.get("capabilities") or [])
    if entry.get("supports_structured_output"):
        capabilities.add("structured_output")
    if entry.get("supports_tools"):
        capabilities.add("tools")
    source = entry.get("pricing_source") or "unknown"
    view = ModelView(
        provider=provider, model_id=model_id, display_name=entry.get("display_name") or model_id,
        family=family_of(provider, model_id), hosting_mode=hosting, capabilities=capabilities,
        context_window=entry.get("context_window"), max_output_tokens=entry.get("max_output_tokens"),
        input_usd_per_mtok=entry.get("input_usd_per_mtok"), output_usd_per_mtok=entry.get("output_usd_per_mtok"),
        cached_usd_per_mtok=entry.get("cached_input_usd_per_mtok"), infra_usd_per_mtok=0.0,
        pricing_status="unknown", pricing_source=source,
        billing_model=entry.get("billing_model") or ("customer" if entry.get("scope") == "organization" else "platform"),
        deprecated=bool(entry.get("deprecated")), api="responses" if "api:responses" in capabilities else "chat",
    )
    if source == "development":
        view.pricing_status = "development"
    elif source in KNOWN_PRICING_SOURCES and view.input_usd_per_mtok is not None and view.output_usd_per_mtok is not None:
        view.pricing_status = "catalog"
    # Self-hosted endpoints have no per-token price; their cost is infrastructure, which only an
    # administrator can supply. Without it, the cost is unknown rather than zero.
    if hosting == "self_hosted" and view.pricing_status == "catalog":
        view.pricing_status = "unknown"
        view.notes.append("Self-hosted: catalog price does not reflect your infrastructure cost")
    # Platform overlays apply first, then the tenant's own (for its BYOK models).
    for overlay in sorted(overlays, key=lambda o: o.scope != "platform"):
        view.enabled = overlay.enabled
        view.priority = overlay.priority
        view.family = overlay.family or view.family
        view.hosting_mode = overlay.hosting_mode or view.hosting_mode
        view.rate_limit_rpm = overlay.rate_limit_rpm or view.rate_limit_rpm
        view.capabilities |= set(overlay.capabilities_add or [])
        view.capabilities -= set(overlay.capabilities_remove or [])
        if overlay.validated_input_usd_per_mtok is not None and overlay.validated_output_usd_per_mtok is not None:
            view.input_usd_per_mtok = overlay.validated_input_usd_per_mtok
            view.output_usd_per_mtok = overlay.validated_output_usd_per_mtok
            view.cached_usd_per_mtok = overlay.validated_cached_usd_per_mtok
            view.pricing_status = "admin_validated"
            view.pricing_source = "admin"
        if overlay.infra_usd_per_mtok is not None:
            view.infra_usd_per_mtok = overlay.infra_usd_per_mtok
            if view.hosting_mode == "self_hosted" and view.pricing_status == "unknown":
                # Self-hosted inference has no token price; its whole cost is the infrastructure.
                view.input_usd_per_mtok = view.output_usd_per_mtok = 0.0
                view.cached_usd_per_mtok = None
                view.pricing_status = "admin_validated"
                view.pricing_source = "admin_infrastructure"
    return view


class Registry:
    """Caches the gateway's model list per tenant for a few seconds."""

    def __init__(self, gateway: Gateway, cache_seconds: float):
        self.gateway = gateway
        self.cache_seconds = cache_seconds
        self._cache: dict[uuid.UUID, tuple[float, list[dict]]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    async def raw(self, identity: Caller) -> list[dict]:
        cached = self._cache.get(identity.tenant_id)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        entries = await self.gateway.models(identity)
        self._cache[identity.tenant_id] = (time.monotonic(), entries)
        return entries

    async def load(self, db: AsyncSession, identity: Caller) -> list[ModelView]:
        entries = await self.raw(identity)
        overlays = list(
            await db.scalars(select(ModelPolicy).where(or_(ModelPolicy.scope == "platform", ModelPolicy.scope == str(identity.tenant_id))))
        )
        by_key: dict[tuple[str, str], list[ModelPolicy]] = {}
        for overlay in overlays:
            by_key.setdefault((overlay.provider, overlay.model_id), []).append(overlay)
        return [build_view(entry, by_key.get((entry["provider"], entry["model_id"]), [])) for entry in entries]
