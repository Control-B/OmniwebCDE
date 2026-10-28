import copy
import secrets
from decimal import Decimal
from typing import Any

import httpx

from ..config import Settings
from ..schemas import Region, Size

MOCK_REGIONS = [
    Region(slug="nyc3", name="New York 3", available=True),
    Region(slug="sfo3", name="San Francisco 3", available=True),
    Region(slug="ams3", name="Amsterdam 3", available=True),
]
MOCK_SIZES = [
    Size(slug="s-1vcpu-1gb", vcpus=1, memory_mb=1024, disk_gb=25, monthly_usd=Decimal("6")),
    Size(slug="s-2vcpu-4gb", vcpus=2, memory_mb=4096, disk_gb=80, monthly_usd=Decimal("24")),
    Size(slug="s-4vcpu-8gb", vcpus=4, memory_mb=8192, disk_gb=160, monthly_usd=Decimal("48")),
]


class DigitalOceanError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DigitalOceanAdapter:
    def __init__(self, token: str, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.digitalocean_base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=20,
        )

    async def __aenter__(self) -> "DigitalOceanAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def validate(self) -> str:
        if self.settings.mock_infrastructure:
            return "mock-account"
        response = await self.client.get("/account")
        self._raise(response)
        account = response.json()["account"]
        if account.get("status") != "active":
            raise DigitalOceanError(
                "account_inactive",
                str(account.get("status_message") or "DigitalOcean account is not active"),
            )
        if account.get("email_verified") is False:
            raise DigitalOceanError(
                "email_unverified", "DigitalOcean account email must be verified"
            )
        if int(account.get("droplet_limit", 0)) < 1:
            raise DigitalOceanError(
                "droplet_quota_exhausted", "DigitalOcean Droplet quota is unavailable"
            )
        return str(account["uuid"])

    async def regions(self) -> list[Region]:
        if self.settings.mock_infrastructure:
            return MOCK_REGIONS
        response = await self.client.get("/regions", params={"per_page": 200})
        self._raise(response)
        return [
            Region(slug=item["slug"], name=item["name"], available=item["available"])
            for item in response.json()["regions"]
        ]

    async def sizes(self, region: str | None = None) -> list[Size]:
        if self.settings.mock_infrastructure:
            return MOCK_SIZES
        response = await self.client.get("/sizes", params={"per_page": 200})
        self._raise(response)
        items = response.json()["sizes"]
        return [
            Size(
                slug=item["slug"],
                vcpus=item["vcpus"],
                memory_mb=item["memory"],
                disk_gb=item["disk"],
                monthly_usd=Decimal(str(item["price_monthly"])),
                available=region in item["regions"] if region else bool(item["available"]),
            )
            for item in items
            if not region or region in item["regions"]
        ]

    async def create_droplet(
        self, *, name: str, region: str, size: str, image: str, user_data: str, tags: list[str]
    ) -> tuple[str, str | None]:
        if self.settings.mock_infrastructure:
            return f"mock-{name}", f"mock-action-{name}"
        response = await self.client.post(
            "/droplets",
            json={
                "name": name,
                "region": region,
                "size": size,
                "image": image,
                "user_data": user_data,
                "monitoring": True,
                "ipv6": False,
                "tags": tags,
            },
        )
        self._raise(response)
        body = response.json()
        actions = body.get("links", {}).get("actions", [])
        action_id = str(actions[0]["id"]) if actions else None
        return str(body["droplet"]["id"]), action_id

    async def action(self, action_id: str) -> dict[str, Any]:
        response = await self.client.get(f"/actions/{action_id}")
        self._raise(response)
        return dict(response.json()["action"])

    async def droplets_by_tag(self, tag: str) -> list[dict[str, Any]]:
        response = await self.client.get("/droplets", params={"tag_name": tag, "per_page": 200})
        self._raise(response)
        return list(response.json()["droplets"])

    async def delete_droplet(self, resource_id: str) -> None:
        if self.settings.mock_infrastructure:
            return
        response = await self.client.delete(f"/droplets/{resource_id}")
        if response.status_code != 404:
            self._raise(response)

    # -- App Platform (generated-app deployments) -------------------------------------------

    async def upsert_app(
        self, spec: dict[str, Any], app_id: str | None = None
    ) -> tuple[str, str | None]:
        """Creates or updates an App Platform app. Returns (app id, deployment id)."""
        spec = copy.deepcopy(spec)
        if self.settings.mock_infrastructure:
            return app_id or f"mock-app-{spec['name']}", f"mock-deployment-{secrets.token_hex(4)}"
        existing: dict[str, str] = {}
        if app_id:
            current = await self.client.get(f"/apps/{app_id}")
            self._raise(current)
            for component in current.json()["app"]["spec"].get("services", []):
                for env in component.get("envs", []):
                    if env.get("type") == "SECRET" and env.get("value"):
                        existing[f"{component['name']}:{env['key']}"] = env["value"]
        for component in spec.get("services", []):
            for env in component.get("envs", []):
                if env.get("type") == "SECRET" and not env.get("value"):
                    # App Platform encrypts SECRET values; reuse the stored ciphertext on updates.
                    env["value"] = existing.get(
                        f"{component['name']}:{env['key']}"
                    ) or secrets.token_urlsafe(32)
        if app_id:
            response = await self.client.put(f"/apps/{app_id}", json={"spec": spec})
        else:
            response = await self.client.post("/apps", json={"spec": spec})
        self._raise(response)
        app = response.json()["app"]
        deployment = app.get("pending_deployment") or app.get("in_progress_deployment") or {}
        return str(app["id"]), deployment.get("id")

    async def app_deployment(self, app_id: str, deployment_id: str) -> dict[str, Any]:
        if self.settings.mock_infrastructure:
            return {
                "id": deployment_id,
                "phase": "ACTIVE",
                "live_url": f"https://{app_id.removeprefix('mock-app-')}.mock.ondigitalocean.app",
            }
        response = await self.client.get(f"/apps/{app_id}/deployments/{deployment_id}")
        self._raise(response)
        deployment = response.json()["deployment"]
        app = await self.client.get(f"/apps/{app_id}")
        self._raise(app)
        return {
            "id": deployment["id"],
            "phase": deployment.get("phase"),
            "live_url": app.json()["app"].get("live_url"),
        }

    async def rollback_app(self, app_id: str, deployment_id: str) -> str:
        if self.settings.mock_infrastructure:
            return f"mock-rollback-{deployment_id}"
        response = await self.client.post(
            f"/apps/{app_id}/rollback", json={"deployment_id": deployment_id, "skip_pin": False}
        )
        self._raise(response)
        return str(response.json()["deployment"]["id"])

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        retryable = response.status_code in {408, 429, 500, 502, 503, 504}
        try:
            body: dict[str, Any] = response.json()
            message = body.get("message", "DigitalOcean request failed")
            code = body.get("id", f"http_{response.status_code}")
        except ValueError:
            message, code = "DigitalOcean request failed", f"http_{response.status_code}"
        raise DigitalOceanError(str(code), str(message), retryable)
