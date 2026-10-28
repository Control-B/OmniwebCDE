"""Provider catalog and model discovery.

Model identifiers are never hardcoded: each provider's list-models API is the source of truth,
and pricing comes from the provider (OpenRouter) or LiteLLM's bundled cost map.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    kind: str  # "hosted" or "self_hosted"
    litellm_prefix: str
    cost_map_prefix: str
    default_base_url: str
    needs_key: bool = True
    needs_base_url: bool = False


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec("openai", "OpenAI", "hosted", "openai", "", "https://api.openai.com/v1"),
    "anthropic": ProviderSpec("anthropic", "Anthropic", "hosted", "anthropic", "", "https://api.anthropic.com/v1"),
    "gemini": ProviderSpec("gemini", "Google Gemini", "hosted", "gemini", "gemini/", "https://generativelanguage.googleapis.com/v1beta"),
    "xai": ProviderSpec("xai", "xAI (Grok)", "hosted", "xai", "xai/", "https://api.x.ai/v1"),
    "openrouter": ProviderSpec("openrouter", "OpenRouter", "hosted", "openrouter", "openrouter/", "https://openrouter.ai/api/v1"),
    "openai_compatible": ProviderSpec("openai_compatible", "OpenAI-compatible endpoint", "self_hosted", "openai", "", "", needs_key=False, needs_base_url=True),
    "ollama": ProviderSpec("ollama", "Ollama", "self_hosted", "ollama_chat", "ollama/", "", needs_key=False, needs_base_url=True),
}

DEV_PROVIDER = "omniweb_dev"

NON_CHAT = re.compile(
    r"embed|whisper|tts|dall-e|moderation|transcribe|audio|realtime|image|search|babbage|davinci|computer-use|sora|codex-mini",
    re.IGNORECASE,
)


@dataclass
class DiscoveredModel:
    model_id: str
    display_name: str = ""
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool = False
    supports_structured_output: bool = False
    capabilities: list[str] = field(default_factory=list)
    input_usd_per_mtok: float | None = None
    output_usd_per_mtok: float | None = None
    cached_input_usd_per_mtok: float | None = None
    deprecated: bool = False
    pricing_source: str = "unknown"


def _per_mtok(value: float | str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number * 1_000_000, 6) if number >= 0 else None


def enrich_from_cost_map(spec: ProviderSpec, model: DiscoveredModel) -> DiscoveredModel:
    import litellm

    entry = litellm.model_cost.get(f"{spec.cost_map_prefix}{model.model_id}") or litellm.model_cost.get(model.model_id)
    if not entry:
        return model
    if entry.get("mode") not in (None, "chat", "responses"):
        model.capabilities = [*model.capabilities, f"mode:{entry.get('mode')}"]
    if entry.get("mode") == "responses" and "api:responses" not in model.capabilities:
        # Only available through the Responses API, not Chat Completions.
        model.capabilities = [*model.capabilities, "api:responses"]
    model.context_window = model.context_window or entry.get("max_input_tokens")
    model.max_output_tokens = model.max_output_tokens or entry.get("max_output_tokens")
    model.supports_tools = model.supports_tools or bool(entry.get("supports_function_calling"))
    model.supports_structured_output = model.supports_structured_output or bool(entry.get("supports_response_schema"))
    if model.input_usd_per_mtok is None:
        model.input_usd_per_mtok = _per_mtok(entry.get("input_cost_per_token"))
        model.output_usd_per_mtok = _per_mtok(entry.get("output_cost_per_token"))
        model.cached_input_usd_per_mtok = _per_mtok(entry.get("cache_read_input_token_cost"))
        if model.input_usd_per_mtok is not None:
            model.pricing_source = "litellm"
    for flag, capability in (
        ("supports_vision", "vision"),
        ("supports_prompt_caching", "prompt_caching"),
        ("supports_reasoning", "reasoning"),
    ):
        if entry.get(flag) and capability not in model.capabilities:
            model.capabilities.append(capability)
    deprecation = entry.get("deprecation_date")
    if deprecation:
        try:
            model.deprecated = date.fromisoformat(str(deprecation)) <= datetime.now(UTC).date()
        except ValueError:
            pass
    return model


def _finish(spec: ProviderSpec, models: list[DiscoveredModel]) -> list[DiscoveredModel]:
    finished = []
    for model in models:
        enrich_from_cost_map(spec, model)
        if any(item.startswith("mode:") for item in model.capabilities):
            continue
        if model.supports_tools and "tools" not in model.capabilities:
            model.capabilities.append("tools")
        if model.supports_structured_output and "structured_output" not in model.capabilities:
            model.capabilities.append("structured_output")
        finished.append(model)
    return finished


def parse_openai_like(payload: dict) -> list[DiscoveredModel]:
    return [
        DiscoveredModel(model_id=item["id"], display_name=item["id"])
        for item in payload.get("data", [])
        if item.get("id") and not NON_CHAT.search(item["id"])
    ]


def parse_anthropic(payload: dict) -> list[DiscoveredModel]:
    return [
        DiscoveredModel(
            model_id=item["id"],
            display_name=item.get("display_name") or item["id"],
            context_window=item.get("max_input_tokens"),
            max_output_tokens=item.get("max_tokens"),
        )
        for item in payload.get("data", [])
        if item.get("id")
    ]


def parse_gemini(payload: dict) -> list[DiscoveredModel]:
    models = []
    for item in payload.get("models", []):
        if "generateContent" not in item.get("supportedGenerationMethods", []):
            continue
        model_id = item.get("name", "").removeprefix("models/")
        if not model_id or NON_CHAT.search(model_id):
            continue
        models.append(
            DiscoveredModel(
                model_id=model_id,
                display_name=item.get("displayName") or model_id,
                context_window=item.get("inputTokenLimit"),
                max_output_tokens=item.get("outputTokenLimit"),
            )
        )
    return models


def parse_openrouter(payload: dict) -> list[DiscoveredModel]:
    models = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if not model_id:
            continue
        modalities = item.get("architecture", {}).get("output_modalities") or ["text"]
        if "text" not in modalities:
            continue
        pricing = item.get("pricing", {})
        params = set(item.get("supported_parameters") or [])
        capabilities = []
        if "image" in (item.get("architecture", {}).get("input_modalities") or []):
            capabilities.append("vision")
        if "reasoning" in params:
            capabilities.append("reasoning")
        input_price = _per_mtok(pricing.get("prompt"))
        models.append(
            DiscoveredModel(
                model_id=model_id,
                display_name=item.get("name") or model_id,
                context_window=item.get("context_length"),
                max_output_tokens=(item.get("top_provider") or {}).get("max_completion_tokens"),
                supports_tools="tools" in params,
                supports_structured_output=bool({"structured_outputs", "response_format"} & params),
                capabilities=capabilities,
                input_usd_per_mtok=input_price,
                output_usd_per_mtok=_per_mtok(pricing.get("completion")),
                cached_input_usd_per_mtok=_per_mtok(pricing.get("input_cache_read")),
                pricing_source="provider" if input_price is not None else "unknown",
            )
        )
    return models


def parse_ollama(payload: dict) -> list[DiscoveredModel]:
    return [
        DiscoveredModel(model_id=item["name"], display_name=item["name"], input_usd_per_mtok=0, output_usd_per_mtok=0, pricing_source="self_hosted")
        for item in payload.get("models", [])
        if item.get("name") and not NON_CHAT.search(item["name"])
    ]


async def discover(spec: ProviderSpec, api_key: str, base_url: str, client: httpx.AsyncClient) -> list[DiscoveredModel]:
    base = (base_url or spec.default_base_url).rstrip("/")
    headers: dict[str, str] = {}
    if spec.name == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        response = await client.get(f"{base}/models", headers=headers, params={"limit": 1000})
        parser = parse_anthropic
    elif spec.name == "gemini":
        response = await client.get(f"{base}/models", headers={"x-goog-api-key": api_key}, params={"pageSize": 1000})
        parser = parse_gemini
    elif spec.name == "ollama":
        response = await client.get(f"{base}/api/tags")
        parser = parse_ollama
    else:
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        response = await client.get(f"{base}/models", headers=headers)
        parser = parse_openrouter if spec.name == "openrouter" else parse_openai_like
    response.raise_for_status()
    models = _finish(spec, parser(response.json()))
    if spec.kind == "self_hosted":
        for model in models:
            if model.input_usd_per_mtok is None:
                model.input_usd_per_mtok = model.output_usd_per_mtok = 0
                model.pricing_source = "self_hosted"
    return models


def litellm_model_name(provider: str, model_id: str) -> str:
    return f"{PROVIDERS[provider].litellm_prefix}/{model_id}"
