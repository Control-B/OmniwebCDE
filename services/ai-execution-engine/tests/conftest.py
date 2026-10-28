import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_data = tempfile.mkdtemp(prefix="aaee-test-")
os.environ["AAEE_DATABASE_URL"] = f"sqlite+aiosqlite:///{_db.name}"
os.environ["AAEE_DATA_DIR"] = _data
os.environ["AAEE_REGISTRY_CACHE_SECONDS"] = "0"

from aaee.inference_gateway import ChatResult, GatewayError  # noqa: E402
from aaee.security import AUDIENCE, DEV_SERVICE_SECRET  # noqa: E402

# Fixture registry entries. Prices here are test fixtures, not claims about real providers.
MODELS = [
    {"provider": "openrouter", "model_id": "openai/gpt-oss-20b", "scope": "platform", "capabilities": ["structured_output"],
     "context_window": 131_072, "max_output_tokens": 32_768, "supports_structured_output": True,
     "input_usd_per_mtok": 0.05, "output_usd_per_mtok": 0.2, "pricing_source": "provider", "billing_model": "platform"},
    {"provider": "openrouter", "model_id": "openai/gpt-oss-120b", "scope": "platform", "capabilities": ["structured_output"],
     "context_window": 131_072, "max_output_tokens": 32_768, "supports_structured_output": True,
     "input_usd_per_mtok": 0.1, "output_usd_per_mtok": 0.5, "pricing_source": "provider", "billing_model": "platform"},
    {"provider": "openai", "model_id": "gpt-5-mini", "scope": "platform", "capabilities": ["structured_output", "tools"],
     "context_window": 400_000, "max_output_tokens": 128_000, "supports_structured_output": True,
     "input_usd_per_mtok": 0.25, "output_usd_per_mtok": 2.0, "pricing_source": "litellm", "billing_model": "platform"},
    {"provider": "openai", "model_id": "gpt-5", "scope": "platform", "capabilities": ["structured_output", "tools", "reasoning"],
     "context_window": 400_000, "max_output_tokens": 128_000, "supports_structured_output": True,
     "input_usd_per_mtok": 1.25, "output_usd_per_mtok": 10.0, "pricing_source": "litellm", "billing_model": "platform"},
    {"provider": "xai", "model_id": "grok-code-fast-1", "scope": "platform", "capabilities": ["structured_output", "tools"],
     "context_window": 256_000, "max_output_tokens": 32_000, "supports_structured_output": True,
     "input_usd_per_mtok": 0.2, "output_usd_per_mtok": 1.5, "pricing_source": "litellm", "billing_model": "platform"},
    {"provider": "xai", "model_id": "grok-4", "scope": "platform", "capabilities": ["structured_output", "tools", "reasoning"],
     "context_window": 256_000, "max_output_tokens": 64_000, "supports_structured_output": True,
     "input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0, "pricing_source": "litellm", "billing_model": "platform"},
    {"provider": "openrouter", "model_id": "mystery/unpriced-model", "scope": "platform", "capabilities": [],
     "context_window": 64_000, "max_output_tokens": 8_000, "input_usd_per_mtok": None, "output_usd_per_mtok": None,
     "pricing_source": "unknown", "billing_model": "platform"},
]


class FakeGateway:
    """Deterministic stand-in for the model gateway. No paid inference in ordinary CI."""

    def __init__(self):
        self.models_list = [dict(m) for m in MODELS]
        self.budget_rows = [{"scope": "organization_monthly", "limit_usd": 100.0, "spent_usd": 0.0, "remaining_usd": 100.0, "hard_limit": True}]
        self.responses: dict[str, list] = {}  # model key -> queue of str | GatewayError
        self.default_response = '{"ok": true}'
        self.calls: list[dict] = []
        self.cancelled: list[str] = []

    def script(self, key: str, *responses) -> None:
        self.responses.setdefault(key, []).extend(responses)

    async def models(self, identity):
        return self.models_list

    async def budgets(self, identity, project_id):
        return self.budget_rows

    async def chat(self, identity, project_id, *, model, messages, max_output_tokens, task_budget_usd, response_format, request_id, attribution):
        self.calls.append({"model": model, "messages": messages, "task_budget_usd": task_budget_usd, "attribution": attribution,
                           "tenant": identity.tenant_id, "max_output_tokens": max_output_tokens})
        queue = self.responses.get(model)
        response = queue.pop(0) if queue else self.default_response
        if isinstance(response, GatewayError):
            raise response
        entry = next(m for m in self.models_list if f"{m['provider']}/{m['model_id']}" == model)
        input_tokens, output_tokens = 1_000, 200
        cost = (input_tokens * (entry["input_usd_per_mtok"] or 0) + output_tokens * (entry["output_usd_per_mtok"] or 0)) / 1_000_000
        return ChatResult(content=response, provider=entry["provider"], model_id=entry["model_id"], billing_model=entry["billing_model"],
                          input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=0, cost_usd=cost, latency_ms=40,
                          request_id=request_id)

    async def cancel(self, identity, request_id):
        self.cancelled.append(request_id)


def token(org: uuid.UUID, user: uuid.UUID | None = None, project: uuid.UUID | None = None, role: str = "owner", padmin: bool = False) -> str:
    now = datetime.now(UTC)
    claims = {"org": str(org), "role": role, "aud": AUDIENCE, "iat": now, "exp": now + timedelta(minutes=5), "padmin": padmin}
    if user:
        claims["user"] = str(user)
    if project:
        claims["project"] = str(project)
    return jwt.encode(claims, DEV_SERVICE_SECRET, algorithm="HS256")


def headers(org: uuid.UUID, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(org, **kwargs)}"}


@pytest.fixture
def org() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def gateway():
    from aaee.main import app
    from aaee.model_registry import Registry

    fake = FakeGateway()
    previous = (app.state.gateway, app.state.registry)
    app.state.gateway = fake
    app.state.registry = Registry(fake, 0)
    yield fake
    app.state.gateway, app.state.registry = previous


@pytest.fixture
def client(gateway):
    from fastapi.testclient import TestClient

    from aaee.main import app

    with TestClient(app) as test_client:
        yield test_client
