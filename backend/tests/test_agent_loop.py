import pytest

from app.config import get_settings
from app.builder.store import StoreError
from app.services.agent_loop import ToolDenied, WorkspaceTools


def tools() -> WorkspaceTools:
    return WorkspaceTools(
        get_settings(),
        None,  # type: ignore[arg-type] -- path/authorization checks do not touch the store
        allowed_paths=["apps/web"],
        allowed_commands=["npm", "pytest"],
    )


def test_agent_tools_enforce_authorized_paths():
    workspace = tools()
    assert workspace.path("apps/web/src/App.tsx") == "apps/web/src/App.tsx"
    with pytest.raises(ToolDenied, match="outside"):
        workspace.path("services/api/.env")
    with pytest.raises(StoreError):
        workspace.path("../../etc/passwd")


@pytest.mark.asyncio
async def test_agent_tools_reject_unknown_and_denied_commands():
    workspace = tools()
    with pytest.raises(ToolDenied, match="Unknown"):
        await workspace.execute("open_network", {})
    with pytest.raises(ToolDenied, match="not authorized"):
        await workspace.execute("run_command", {"command": ["curl", "https://example.com"]})
    with pytest.raises(ToolDenied, match="not authorized"):
        await workspace.execute("run_tests", {"command": ["bash", "-lc", "pytest"]})
