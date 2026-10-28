import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import ModelEntry, ProviderCredential
from .providers import DEV_PROVIDER, PROVIDERS, discover
from .security import decrypt

PLATFORM = "platform"


@dataclass(frozen=True)
class ResolvedCredential:
    provider: str
    api_key: str
    base_url: str
    billing_model: str  # "platform" or "customer"
    scope: str


def platform_credential(provider: str, settings: Settings) -> ResolvedCredential | None:
    values = {
        "openai": (settings.openai_api_key, ""),
        "anthropic": (settings.anthropic_api_key, ""),
        "gemini": (settings.gemini_api_key, ""),
        "openrouter": (settings.openrouter_api_key, ""),
        "openai_compatible": (settings.openai_compatible_api_key, settings.openai_compatible_base_url),
        "ollama": ("", settings.ollama_base_url),
    }
    key, base_url = values[provider]
    spec = PROVIDERS[provider]
    if (spec.needs_key and not key) or (spec.needs_base_url and not base_url):
        return None
    return ResolvedCredential(provider, key, base_url, "platform", PLATFORM)


async def customer_credential(
    db: AsyncSession, organization_id: uuid.UUID, provider: str, settings: Settings
) -> ResolvedCredential | None:
    stored = await db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == organization_id,
            ProviderCredential.provider == provider,
        )
    )
    if not stored:
        return None
    key = decrypt(stored.encrypted_key, settings) if stored.encrypted_key else ""
    return ResolvedCredential(provider, key, stored.base_url, "customer", str(organization_id))


async def credentials_for(
    db: AsyncSession, organization_id: uuid.UUID | None, settings: Settings
) -> dict[str, ResolvedCredential]:
    """Customer keys take precedence so customers who bring a key are billed by their provider."""
    resolved: dict[str, ResolvedCredential] = {}
    for provider in PROVIDERS:
        credential = None
        if organization_id:
            credential = await customer_credential(db, organization_id, provider, settings)
        credential = credential or platform_credential(provider, settings)
        if credential:
            resolved[provider] = credential
    return resolved


async def upsert_models(db: AsyncSession, provider: str, scope: str, discovered, routable: bool) -> int:
    existing = {
        entry.model_id: entry
        for entry in await db.scalars(
            select(ModelEntry).where(ModelEntry.provider == provider, ModelEntry.scope == scope)
        )
    }
    seen = set()
    verified = datetime.now(UTC)
    for model in discovered:
        seen.add(model.model_id)
        entry = existing.get(model.model_id) or ModelEntry(provider=provider, model_id=model.model_id, scope=scope)
        entry.display_name = model.display_name or model.model_id
        entry.capabilities = sorted(set(model.capabilities))
        entry.context_window = model.context_window
        entry.max_output_tokens = model.max_output_tokens
        entry.supports_tools = model.supports_tools
        entry.supports_structured_output = model.supports_structured_output
        entry.input_usd_per_mtok = model.input_usd_per_mtok
        entry.output_usd_per_mtok = model.output_usd_per_mtok
        entry.cached_input_usd_per_mtok = model.cached_input_usd_per_mtok
        entry.deprecated = model.deprecated
        entry.pricing_source = model.pricing_source
        entry.available = True
        entry.routable = routable
        entry.last_verified_at = verified
        db.add(entry)
    for model_id, entry in existing.items():
        if model_id not in seen:
            entry.available = False
    await db.flush()
    return len(seen)


async def refresh(
    db: AsyncSession, organization_id: uuid.UUID | None, settings: Settings, client: httpx.AsyncClient
) -> dict[str, dict]:
    results: dict[str, dict] = {}
    credentials = await credentials_for(db, organization_id, settings)
    for provider, credential in credentials.items():
        try:
            discovered = await discover(PROVIDERS[provider], credential.api_key, credential.base_url, client)
            count = await upsert_models(db, provider, credential.scope, discovered, routable=True)
            results[provider] = {"status": "ok", "models": count, "billing_model": credential.billing_model}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            results[provider] = {"status": "error", "error": type(exc).__name__}
    if "openrouter" not in credentials and settings.openrouter_public_catalog:
        try:
            discovered = await discover(PROVIDERS["openrouter"], "", "", client)
            count = await upsert_models(db, "openrouter", PLATFORM, discovered, routable=False)
            results["openrouter"] = {"status": "catalog_only", "models": count}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            results["openrouter"] = {"status": "error", "error": type(exc).__name__}
    await db.commit()
    return results


async def seed_dev_models(db: AsyncSession, settings: Settings) -> None:
    if not settings.mock_mode or settings.is_production:
        return
    for model_id, name in (("dev-fast", "Omniweb development model (no AI)"),):
        exists = await db.scalar(
            select(ModelEntry).where(ModelEntry.provider == DEV_PROVIDER, ModelEntry.model_id == model_id)
        )
        if not exists:
            db.add(
                ModelEntry(
                    provider=DEV_PROVIDER,
                    model_id=model_id,
                    scope=PLATFORM,
                    display_name=name,
                    capabilities=["development"],
                    context_window=32_000,
                    max_output_tokens=4_096,
                    input_usd_per_mtok=0,
                    output_usd_per_mtok=0,
                    pricing_source="development",
                )
            )
    await db.commit()
