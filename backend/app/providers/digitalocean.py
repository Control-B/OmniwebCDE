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
        return str(response.json()["account"]["uuid"])

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
    ) -> str:
        if self.settings.mock_infrastructure:
            return f"mock-{name}"
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
        return str(response.json()["droplet"]["id"])

    async def delete_droplet(self, resource_id: str) -> None:
        if self.settings.mock_infrastructure:
            return
        response = await self.client.delete(f"/droplets/{resource_id}")
        if response.status_code != 404:
            self._raise(response)

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
