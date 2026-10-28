import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import security
from app.config import get_settings
from app.main import app

ISSUER = "https://id.example.test/realms/omniweb"


class StubJwks:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _token):
        return self


@pytest.fixture
def oidc(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(security, "jwks_client", lambda _base: StubJwks(private_key.public_key()))

    def issue(**overrides):
        now = datetime.now(UTC)
        claims = {
            "iss": ISSUER,
            "aud": "omniweb-api",
            "sub": f"user-{uuid.uuid4().hex[:8]}",
            "email": "jordan@acme.test",
            "name": "Jordan Lee",
            "org_id": str(uuid.uuid4()),
            "realm_access": {"roles": ["offline_access", "member", "admin"]},
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        claims.update(overrides)
        return jwt.encode(
            {k: v for k, v in claims.items() if v is not None}, private_key, algorithm="RS256"
        )

    return issue


def test_oidc_users_are_persisted_with_highest_realm_role(oidc):
    token = oidc()
    with TestClient(app) as client:
        first = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert first.status_code == 200, first.text
        body = first.json()
        assert (
            body["auth_mode"] == "oidc"
            and body["role"] == "admin"
            and body["display_name"] == "Jordan Lee"
        )
        again = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert again["user_id"] == body["user_id"]
        project = client.post(
            "/api/v1/projects",
            json={"prompt": "OIDC user project"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert project.status_code == 201


@pytest.mark.parametrize(
    "override", [{"aud": "someone-else"}, {"iss": "https://evil.test"}, {"org_id": None}]
)
def test_tokens_with_wrong_audience_issuer_or_tenant_are_rejected(oidc, override):
    with TestClient(app) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {oidc(**override)}"})
        assert response.status_code == 401
