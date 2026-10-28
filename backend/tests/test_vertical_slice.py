import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Principal
from app.security import get_principal


def test_workspace_creation_is_idempotent() -> None:
    with TestClient(app) as client:
        connection = client.post(
            "/api/v1/cloud-connections",
            json={"label": "Engineering", "token": "dop_v1_mock_token"},
        )
        assert connection.status_code == 201
        payload = {
            "name": "payments-api",
            "cloud_connection_id": connection.json()["id"],
            "region": "nyc3",
            "size": "s-2vcpu-4gb",
            "image": "ubuntu-24-04-x64",
            "template": "full-stack",
            "idempotency_key": "create-payments-api-001",
            "approved_estimated_monthly_usd": "24.00",
        }
        first = client.post("/api/v1/workspaces", json=payload)
        second = client.post("/api/v1/workspaces", json=payload)
        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["state"] == "READY"


def test_cross_tenant_workspace_access_is_hidden() -> None:
    with TestClient(app) as client:
        connection = client.post(
            "/api/v1/cloud-connections",
            json={"label": "Isolation", "token": "dop_v1_isolation"},
        ).json()
        workspace = client.post(
            "/api/v1/workspaces",
            json={
                "name": "private-space",
                "cloud_connection_id": connection["id"],
                "region": "nyc3",
                "size": "s-1vcpu-1gb",
                "idempotency_key": "private-space-create",
                "approved_estimated_monthly_usd": "6.00",
            },
        ).json()

        async def other_tenant() -> Principal:
            return Principal(
                user_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                email="intruder@example.com",
                role="owner",
            )

        app.dependency_overrides[get_principal] = other_tenant
        try:
            response = client.get(f"/api/v1/workspaces/{workspace['id']}")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


def test_price_changes_require_new_approval() -> None:
    with TestClient(app) as client:
        connection = client.post(
            "/api/v1/cloud-connections",
            json={"label": "Pricing", "token": "dop_v1_pricing_token"},
        ).json()
        response = client.post(
            "/api/v1/workspaces",
            json={
                "name": "price-check",
                "cloud_connection_id": connection["id"],
                "region": "nyc3",
                "size": "s-1vcpu-1gb",
                "idempotency_key": "price-check-create",
                "approved_estimated_monthly_usd": "5.00",
            },
        )
        assert response.status_code == 409
