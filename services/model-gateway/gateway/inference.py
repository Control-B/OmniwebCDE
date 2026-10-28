import hashlib
from dataclasses import dataclass

from .models import ModelEntry
from .providers import DEV_PROVIDER, litellm_model_name
from .registry import ResolvedCredential

PROMPT_CACHE_MIN_CHARS = 4_000


@dataclass
class Completion:
    content: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int


class ProviderError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def estimate_tokens(messages: list[dict]) -> int:
    return int(sum(len(str(message.get("content", ""))) for message in messages) / 3.5) + 8 * len(messages)


def cost(entry: ModelEntry, completion: Completion) -> float:
    uncached = max(0, completion.input_tokens - completion.cached_tokens)
    cached_price = entry.cached_input_usd_per_mtok
    if cached_price is None:
        cached_price = entry.input_usd_per_mtok or 0
    return round(
        (
            uncached * (entry.input_usd_per_mtok or 0)
            + completion.cached_tokens * cached_price
            + completion.output_tokens * (entry.output_usd_per_mtok or 0)
        )
        / 1_000_000,
        8,
    )


def _with_prompt_cache(entry: ModelEntry, messages: list[dict]) -> list[dict]:
    # Anthropic requires explicit cache breakpoints; OpenAI and Gemini cache automatically.
    if entry.provider != "anthropic" or "prompt_caching" not in entry.capabilities:
        return messages
    prepared = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "system" and isinstance(content, str) and len(content) >= PROMPT_CACHE_MIN_CHARS:
            message = {**message, "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]}
        prepared.append(message)
    return prepared


def _dev_completion(messages: list[dict]) -> Completion:
    last = next((m for m in reversed(messages) if m.get("role") == "user"), {"content": ""})
    text = str(last.get("content", "")).strip()
    words = len(text.split())
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    content = (
        "Development model: no AI provider is configured, so this reply is generated locally "
        f"without a language model. I received your message ({words} words, ref {digest}). "
        "An organization admin can add a provider key under Usage → Providers to get real responses."
    )
    return Completion(content, estimate_tokens(messages), int(len(content) / 3.5), 0)


async def complete(
    entry: ModelEntry,
    credential: ResolvedCredential | None,
    messages: list[dict],
    max_output_tokens: int,
    timeout: float,
    response_format: dict | None = None,
) -> Completion:
    if entry.provider == DEV_PROVIDER:
        return _dev_completion(messages)
    if not credential:
        raise ProviderError("no_credentials", "No credentials for provider")
    import litellm

    kwargs: dict = {
        "model": litellm_model_name(entry.provider, entry.model_id),
        "messages": _with_prompt_cache(entry, messages),
        "max_tokens": max_output_tokens,
        "timeout": timeout,
        "num_retries": 0,
    }
    if credential.api_key:
        kwargs["api_key"] = credential.api_key
    if credential.base_url:
        kwargs["api_base"] = credential.base_url
    if response_format and entry.supports_structured_output:
        kwargs["response_format"] = response_format
    if "api:responses" in (entry.capabilities or []):
        return await _responses(litellm, kwargs)
    try:
        response = await litellm.acompletion(**kwargs)
    except litellm.exceptions.AuthenticationError as exc:
        raise ProviderError("authentication", "Provider rejected the credentials") from exc
    except litellm.exceptions.RateLimitError as exc:
        raise ProviderError("rate_limited", "Provider rate limit reached") from exc
    except litellm.exceptions.ContextWindowExceededError as exc:
        raise ProviderError("context_window", "Request exceeds the model context window") from exc
    except litellm.exceptions.Timeout as exc:
        raise ProviderError("timeout", "Provider request timed out") from exc
    except Exception as exc:  # LiteLLM maps provider failures onto many exception types.
        raise ProviderError("provider_error", f"{type(exc).__name__} {getattr(exc, 'status_code', '')}".strip()) from exc
    usage = getattr(response, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None)
    return Completion(
        content=response.choices[0].message.content or "",
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        cached_tokens=getattr(details, "cached_tokens", 0) or 0,
    )


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def parse_responses_output(response) -> Completion:
    texts = []
    for item in _field(response, "output", []) or []:
        if _field(item, "type") != "message":
            continue
        for part in _field(item, "content", []) or []:
            if _field(part, "type") == "output_text":
                texts.append(_field(part, "text", "") or "")
    usage = _field(response, "usage")
    details = _field(usage, "input_tokens_details")
    return Completion(
        content="".join(texts),
        input_tokens=_field(usage, "input_tokens", 0) or 0,
        output_tokens=_field(usage, "output_tokens", 0) or 0,
        cached_tokens=_field(details, "cached_tokens", 0) or 0,
    )


async def _responses(litellm, kwargs: dict) -> Completion:
    """Models that the cost map lists in `responses` mode use the OpenAI Responses API."""
    request = {
        "model": kwargs["model"],
        "input": kwargs["messages"],
        "max_output_tokens": kwargs["max_tokens"],
        "timeout": kwargs["timeout"],
    }
    for key in ("api_key", "api_base"):
        if key in kwargs:
            request[key] = kwargs[key]
    format_ = kwargs.get("response_format")
    if format_ and format_.get("type") == "json_schema":
        request["text"] = {"format": {"type": "json_schema", **format_.get("json_schema", {})}}
    elif format_ and format_.get("type") == "json_object":
        request["text"] = {"format": {"type": "json_object"}}
    try:
        response = await litellm.aresponses(**request)
    except litellm.exceptions.AuthenticationError as exc:
        raise ProviderError("authentication", "Provider rejected the credentials") from exc
    except litellm.exceptions.RateLimitError as exc:
        raise ProviderError("rate_limited", "Provider rate limit reached") from exc
    except litellm.exceptions.Timeout as exc:
        raise ProviderError("timeout", "Provider request timed out") from exc
    except Exception as exc:  # LiteLLM maps provider failures onto many exception types.
        raise ProviderError("provider_error", f"{type(exc).__name__} {getattr(exc, 'status_code', '')}".strip()) from exc
    return parse_responses_output(response)

