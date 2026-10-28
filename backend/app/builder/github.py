"""Two-way sync between a project's repository and GitHub.

With a GitHub App configured (OMNIWEB_GITHUB_APP_ID / OMNIWEB_GITHUB_APP_PRIVATE_KEY), Omniweb
mints a short-lived installation token per operation and hands it to git through environment-only
configuration (an Authorization extra header). Tokens never appear in remote URLs, git config
files, the repository, logs, or the browser.

Without an app, a local bare repository under the builder data directory stands in for GitHub,
so the whole flow (push, pull, merge, conflicts) can be exercised offline.

Sync never force-pushes and never overwrites work: pushes fail if GitHub has commits Omniweb
hasn't merged, and pulls merge; on conflict the merge is aborted and the conflicting files are
reported.
"""

import base64
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

from ..config import Settings
from .store import ProjectStore, StoreError
from .toolchain import data_dir

REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
BRANCH = re.compile(r"^(?!.*\.\.)(?!/)[A-Za-z0-9._/-]{1,100}(?<!/)(?<!\.lock)$")


class SyncError(RuntimeError):
    def __init__(self, message: str, conflicts: list[str] | None = None):
        super().__init__(message)
        self.conflicts = conflicts or []


@dataclass
class Remote:
    url: str
    env: dict[str, str]
    mode: str


def mode(settings: Settings) -> str:
    return "github" if settings.github_app_id and settings.github_app_private_key else "local"


def validate(repo: str, branch: str) -> None:
    if not REPO.match(repo):
        raise SyncError("Use the owner/name form, like acme/keyhold")
    if not BRANCH.match(branch):
        raise SyncError("That isn't a valid branch name")


def local_remote(settings: Settings, repo: str) -> Path:
    return data_dir(settings) / "remotes" / f"{repo}.git"


async def _installation_token(settings: Settings, installation_id: str, repo: str) -> str:
    issued = int(time.time())
    app_jwt = jwt.encode({"iat": issued - 60, "exp": issued + 540, "iss": settings.github_app_id}, settings.github_app_private_key, algorithm="RS256")
    async with httpx.AsyncClient(base_url=settings.github_api_url, timeout=20) as client:
        response = await client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            json={"repositories": [repo.split("/", 1)[1]], "permissions": {"contents": "write"}},
        )
    if response.status_code != 201:
        raise SyncError("GitHub refused the installation token. Check that the Omniweb app is installed on this repository.")
    return response.json()["token"]


async def remote(settings: Settings, repo: str, installation_id: str | None) -> Remote:
    if mode(settings) == "local":
        path = local_remote(settings, repo)
        return Remote(url=str(path), env={}, mode="local")
    if not installation_id:
        raise SyncError("Install the Omniweb GitHub App on this repository, then connect it again.")
    token = await _installation_token(settings, installation_id, repo)
    header = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {header}"}
    return Remote(url=f"https://github.com/{repo}.git", env=env, mode="github")


async def ensure_local_remote(settings: Settings, repo: str, branch: str) -> None:
    path = local_remote(settings, repo)
    if (path / "HEAD").exists():
        return
    path.mkdir(parents=True, exist_ok=True)
    helper = ProjectStore.__new__(ProjectStore)
    helper.repo = path
    helper._home = data_dir(settings) / "git-home"
    await helper.git("init", "-q", "--bare", "-b", branch)


async def _fetch(store: ProjectStore, target: Remote, branch: str) -> str | None:
    code, out = await store.git_status("fetch", "--no-tags", "-q", target.url, f"+refs/heads/{branch}:refs/remotes/github/{branch}", env=target.env)
    if code != 0:
        if "couldn't find remote ref" in out or "not found" in out.lower():
            return None
        raise SyncError(_clean(out) or "Could not reach the repository")
    code, sha = await store.git_status("rev-parse", "--verify", "-q", f"refs/remotes/github/{branch}")
    return sha.strip() if code == 0 else None


def _clean(output: str) -> str:
    return re.sub(r"https://[^@\s]+@", "https://", output).strip()[-500:]


async def status(store: ProjectStore, target: Remote, branch: str) -> dict:
    remote_sha = await _fetch(store, target, branch)
    head = await store.head()
    ahead = behind = 0
    if remote_sha and head:
        _, counts = await store.git_status("rev-list", "--left-right", "--count", f"{head}...{remote_sha}")
        parts = counts.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
    elif head:
        _, count = await store.git_status("rev-list", "--count", head)
        ahead = int(count.strip() or 0)
    return {"remote_sha": remote_sha, "head": head, "ahead": ahead, "behind": behind}


async def push(store: ProjectStore, target: Remote, branch: str) -> dict:
    if await store.dirty():
        raise SyncError("Save or discard your unsaved changes before pushing")
    head = await store.head()
    if not head:
        raise SyncError("Generate the app before pushing it")
    state = await status(store, target, branch)
    if state["behind"]:
        raise SyncError(f"GitHub has {state['behind']} commit(s) Omniweb doesn't have yet. Pull first, then push.")
    code, out = await store.git_status("push", "-q", "--porcelain", target.url, f"HEAD:refs/heads/{branch}", env=target.env)
    if code != 0:
        raise SyncError(_clean(out) or "Push was rejected")
    return {**state, "pushed": head, "ahead": 0}


async def pull(store: ProjectStore, target: Remote, branch: str) -> dict:
    if await store.dirty():
        raise SyncError("Save or discard your unsaved changes before pulling")
    remote_sha = await _fetch(store, target, branch)
    if not remote_sha:
        return {"merged": False, "message": "The branch is empty on GitHub. Push first."}
    head = await store.head()
    if head == remote_sha:
        return {"merged": False, "message": "Already up to date"}
    if head:
        code, _ = await store.git_status("merge-base", "--is-ancestor", remote_sha, head)
        if code == 0:
            return {"merged": False, "message": "Already up to date"}
    if not head:
        await store.git("reset", "-q", "--hard", remote_sha)
        return {"merged": True, "sha": remote_sha, "message": "Imported the repository"}
    identity = {"GIT_AUTHOR_NAME": "Omniweb", "GIT_AUTHOR_EMAIL": "builder@omniweb.local", "GIT_COMMITTER_NAME": "Omniweb", "GIT_COMMITTER_EMAIL": "builder@omniweb.local"}
    code, out = await store.git_status("merge", "--no-edit", "--no-ff", "-m", f"Merge {branch} from GitHub", remote_sha, env=identity)
    if code != 0:
        _, files = await store.git_status("diff", "--name-only", "--diff-filter=U")
        await store.git_status("merge", "--abort")
        conflicts = [f for f in files.splitlines() if f]
        raise SyncError("These files changed both here and on GitHub, so nothing was merged. Resolve them on GitHub or in a cloud workspace, then pull again.", conflicts)
    sha = await store.head()
    return {"merged": True, "sha": sha, "message": "Merged changes from GitHub"}


__all__ = ["SyncError", "StoreError", "mode", "validate", "remote", "ensure_local_remote", "status", "push", "pull"]
