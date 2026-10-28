from gateway.config import Settings
from gateway.models import ModelEntry
from gateway.providers import parse_anthropic, parse_gemini, parse_openai_like, parse_openrouter
from gateway.routing import RouteRequest, candidates, escalation_path

SETTINGS = Settings(economy_max_blended_usd=1.0, standard_max_blended_usd=8.0)


def entry(provider: str, model_id: str, price_in: float | None, price_out: float | None, context: int = 128_000, **kwargs) -> ModelEntry:
    return ModelEntry(
        provider=provider,
        model_id=model_id,
        scope="platform",
        capabilities=kwargs.pop("capabilities", ["tools"]),
        context_window=context,
        input_usd_per_mtok=price_in,
        output_usd_per_mtok=price_out,
        available=kwargs.pop("available", True),
        routable=True,
        deprecated=kwargs.pop("deprecated", False),
    )


CHEAP = entry("openai", "cheap", 0.1, 0.4)
MID = entry("anthropic", "mid", 3, 9)
BIG = entry("gemini", "big", 10, 30, context=1_000_000)
UNPRICED = entry("openrouter", "unpriced", None, None)
LOCAL = entry("openai_compatible", "local", 0, 0, context=32_000)
OLLAMA = entry("ollama", "llama", 0, 0, context=8_000)
DEV = entry("omniweb_dev", "dev-fast", 0, 0)
ALL = [CHEAP, MID, BIG, UNPRICED, LOCAL, OLLAMA, DEV]


def ids(models):
    return [m.model_id for m in models]


def test_tiers_follow_price_bands():
    assert ids(candidates(ALL, RouteRequest(tier="economy"), SETTINGS)) == ["cheap"]
    assert ids(candidates(ALL, RouteRequest(tier="standard"), SETTINGS)) == ["mid", "cheap"]
    assert ids(candidates(ALL, RouteRequest(tier="advanced"), SETTINGS)) == ["big", "mid", "cheap"]
    assert ids(candidates(ALL, RouteRequest(tier="self_hosted"), SETTINGS)) == ["local", "llama"]


def test_hosted_models_without_prices_are_never_routed():
    assert "unpriced" not in ids(candidates(ALL, RouteRequest(tier="advanced"), SETTINGS))


def test_context_capability_and_budget_filters():
    assert ids(candidates(ALL, RouteRequest(tier="advanced", estimated_input_tokens=500_000), SETTINGS)) == ["big"]
    assert ids(candidates(ALL, RouteRequest(tier="advanced", capabilities=["vision"]), SETTINGS)) == []
    budgeted = RouteRequest(tier="advanced", estimated_input_tokens=10_000, max_output_tokens=4_000, remaining_budget_usd=0.01)
    assert ids(candidates(ALL, budgeted, SETTINGS)) == ["cheap"]


def test_pins_providers_and_deprecations():
    pinned = RouteRequest(tier="standard", pinned_model="openai/cheap")
    assert ids(candidates(ALL, pinned, SETTINGS))[0] == "cheap"
    restricted = RouteRequest(tier="advanced", allowed_providers=["anthropic"])
    assert ids(candidates(ALL, restricted, SETTINGS)) == ["mid"]
    old = entry("openai", "old", 0.1, 0.1, deprecated=True)
    assert "old" not in ids(candidates([old, CHEAP], RouteRequest(tier="economy"), SETTINGS))


def test_development_model_only_when_no_real_model_exists():
    assert ids(candidates([DEV], RouteRequest(tier="advanced"), SETTINGS)) == ["dev-fast"]
    assert "dev-fast" not in ids(candidates(ALL, RouteRequest(tier="economy"), SETTINGS))


def test_escalation_is_bounded():
    assert escalation_path("economy", 0) == ["economy"]
    assert escalation_path("economy", 1) == ["economy", "standard"]
    assert escalation_path("standard", 5) == ["standard", "advanced"]
    assert escalation_path("self_hosted", 2) == ["self_hosted"]


def test_discovery_parsers():
    openrouter = parse_openrouter(
        {
            "data": [
                {
                    "id": "vendor/model-a",
                    "name": "Model A",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015", "input_cache_read": "0.0000003"},
                    "supported_parameters": ["tools", "response_format"],
                    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                },
                {"id": "vendor/image-gen", "pricing": {}, "architecture": {"output_modalities": ["image"]}},
            ]
        }
    )
    assert len(openrouter) == 1
    model = openrouter[0]
    assert (model.input_usd_per_mtok, model.output_usd_per_mtok, model.cached_input_usd_per_mtok) == (3.0, 15.0, 0.3)
    assert model.supports_tools and model.supports_structured_output and "vision" in model.capabilities

    gemini = parse_gemini(
        {
            "models": [
                {"name": "models/gemini-x", "inputTokenLimit": 1048576, "outputTokenLimit": 8192, "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-y", "supportedGenerationMethods": ["embedContent"]},
            ]
        }
    )
    assert [m.model_id for m in gemini] == ["gemini-x"] and gemini[0].context_window == 1048576

    anthropic = parse_anthropic({"data": [{"id": "claude-x", "display_name": "Claude X"}]})
    assert anthropic[0].display_name == "Claude X"

    openai = parse_openai_like({"data": [{"id": "gpt-x"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}]})
    assert [m.model_id for m in openai] == ["gpt-x"]


def test_responses_api_output_is_parsed():
    from gateway.inference import parse_responses_output

    response = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "Hello "}, {"type": "output_text", "text": "world"}]},
        ],
        "usage": {"input_tokens": 120, "output_tokens": 8, "input_tokens_details": {"cached_tokens": 100}},
    }
    completion = parse_responses_output(response)
    assert completion.content == "Hello world"
    assert (completion.input_tokens, completion.output_tokens, completion.cached_tokens) == (120, 8, 100)


def test_xai_is_a_discoverable_hosted_provider():
    from gateway.providers import (
        PROVIDERS,
        DiscoveredModel,
        _finish,
        litellm_model_name,
        parse_openai_like,
    )

    assert PROVIDERS["xai"].kind == "hosted"
    models = _finish(PROVIDERS["xai"], parse_openai_like({"data": [{"id": "grok-code-fast-1"}, {"id": "grok-2-image-1212"}]}))
    assert [m.model_id for m in models] == ["grok-code-fast-1"]
    assert isinstance(models[0], DiscoveredModel)
    assert litellm_model_name("xai", "grok-code-fast-1") == "xai/grok-code-fast-1"
