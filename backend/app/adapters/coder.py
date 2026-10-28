from typing import Any, Literal
from urllib.parse import quote

import httpx

from ..config import Settings


class CoderError(RuntimeError):
    def __init__(self, status_code: int, detail: str, retryable: bool = False):
        super().__init__(detail)
        self.status_code = status_code
        self.retryable = retryable


class CoderAdapter:
    """Restricted server-side client for Coder's documented v2 REST API.

    The service token is never serialized into an Omniweb response. Browser access is
    delegated through owner-scoped Coder apps or a separately minted user session.
    """

    def __init__(self, settings: Settings):
        if not settings.coder_token:
            raise CoderError(503, "Coder service account is not configured")
        self.access_url = settings.coder_access_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=settings.coder_base_url.rstrip("/"),
            headers={
                "Coder-Session-Token": settings.coder_token,
                "Accept": "application/json",
            },
            timeout=30,
        )

    async def __aenter__(self) -> "CoderAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def templates(self, organization_id: str) -> list[dict[str, Any]]:
        response = await self.client.get(
            "/api/v2/templates", params={"q": f"organization:{organization_id}"}
        )
        return self._json(response)

    async def create_workspace(
        self,
        *,
        coder_organization_id: str,
        coder_user_id: str,
        name: str,
        template_id: str,
        parameters: dict[str, str],
        ttl_ms: int,
    ) -> dict[str, Any]:
        response = await self.client.post(
            f"/api/v2/organizations/{coder_organization_id}/members/{coder_user_id}/workspaces",
            json={
                "name": name,
                "template_id": template_id,
                "ttl_ms": ttl_ms,
                "automatic_updates": "always",
                "rich_parameter_values": [
                    {"name": key, "value": value} for key, value in parameters.items()
                ],
            },
        )
        return self._json(response)

    async def workspace(self, workspace_id: str) -> dict[str, Any]:
        return self._json(await self.client.get(f"/api/v2/workspaces/{workspace_id}"))

    async def build(
        self,
        workspace_id: str,
        transition: Literal["start", "stop", "delete"],
    ) -> dict[str, Any]:
        response = await self.client.post(
            f"/api/v2/workspaces/{workspace_id}/builds",
            json={"transition": transition, "reason": "dashboard"},
        )
        return self._json(response)

    async def agent_health(self, workspace_id: str) -> dict[str, str]:
        workspace = await self.workspace(workspace_id)
        agents = [
            agent
            for resource in workspace.get("latest_build", {}).get("resources", [])
            for agent in resource.get("agents", [])
        ]
        if not agents:
            return {"status": "missing", "lifecycle_state": "off"}
        agent = agents[0]
        return {
            "status": str(agent.get("status", "unknown")),
            "lifecycle_state": str(agent.get("lifecycle_state", "unknown")),
        }

    async def owner_app(self, workspace_id: str, slug: str = "code") -> dict[str, str]:
        """Return Coder-provided app metadata, never an administrator session token."""
        workspace = await self.workspace(workspace_id)
        for resource in workspace.get("latest_build", {}).get("resources", []):
            for agent in resource.get("agents", []):
                for app in agent.get("apps", []):
                    if app.get("slug") == slug and app.get("sharing_level") == "owner":
                        owner = quote(str(workspace["owner_name"]), safe="")
                        workspace_name = quote(str(workspace["name"]), safe="")
                        app_slug = quote(slug, safe="")
                        return {
                            "slug": slug,
                            "url": (
                                f"{self.access_url}/@{owner}/{workspace_name}/apps/{app_slug}/"
                            ),
                        }
        raise CoderError(404, f"Owner-only app '{slug}' is not available")

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if response.is_success:
            return response.json()
        retryable = response.status_code in {408, 429, 500, 502, 503, 504}
        try:
            detail = response.json().get("message", "Coder request failed")
        except ValueError:
            detail = "Coder request failed"
        raise CoderError(response.status_code, detail, retryable)
