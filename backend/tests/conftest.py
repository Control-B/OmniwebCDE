import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
_scratch = Path(tempfile.mkdtemp(prefix="omniweb-tests-"))
os.environ.setdefault("OMNIWEB_DATABASE_URL", f"sqlite+aiosqlite:///{_scratch / 'api.db'}")
os.environ.setdefault("OMNIWEB_BUILDER_DATA_DIR", str(_scratch / "builder"))
# Reuse the toolchain installed for local development so tests don't reinstall packages.
os.environ.setdefault("OMNIWEB_BUILDER_TOOLCHAIN_DIR", str(ROOT / ".omniweb" / "toolchain"))
os.environ.setdefault("OMNIWEB_MODEL_GATEWAY_URL", "http://127.0.0.1:9")
# Builder tests use the direct gateway path unless a test runs AAEE in-process (live_aaee).
os.environ.setdefault("OMNIWEB_AAEE_URL", "http://127.0.0.1:9")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import gateway as gateway_client  # noqa: E402

GATEWAY_DIR = ROOT.parent / "services" / "model-gateway"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def live_gateway(monkeypatch):
    """Run the real model gateway in-process so the service-token handshake is exercised."""
    database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    os.environ["GATEWAY_DATABASE_URL"] = f"sqlite+aiosqlite:///{database.name}"
    os.environ["GATEWAY_OPENROUTER_PUBLIC_CATALOG"] = "false"
    sys.path.insert(0, str(GATEWAY_DIR))
    from gateway.database import SessionLocal as GatewaySession
    from gateway.database import engine as gateway_engine
    from gateway.main import app as gateway_app
    from gateway.models import Base as GatewayBase
    from gateway.registry import seed_dev_models

    async def prepare():
        async with gateway_engine.begin() as connection:
            await connection.run_sync(GatewayBase.metadata.create_all)
        async with GatewaySession() as db:
            from gateway.config import get_settings as gateway_settings

            await seed_dev_models(db, gateway_settings())
        await gateway_engine.dispose()

    asyncio.run(prepare())
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.ASGITransport(app=gateway_app)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(gateway_client.httpx, "AsyncClient", client_factory)
    yield
    sys.path.remove(str(GATEWAY_DIR))
