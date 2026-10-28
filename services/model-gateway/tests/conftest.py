import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["GATEWAY_DATABASE_URL"] = f"sqlite+aiosqlite:///{_db.name}"
os.environ["GATEWAY_OPENROUTER_PUBLIC_CATALOG"] = "false"

from gateway.security import AUDIENCE, DEV_SERVICE_SECRET  # noqa: E402


def token(org: uuid.UUID, user: uuid.UUID | None = None, project: uuid.UUID | None = None, role: str = "owner") -> str:
    now = datetime.now(UTC)
    claims = {"org": str(org), "role": role, "aud": AUDIENCE, "iat": now, "exp": now + timedelta(minutes=5)}
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
