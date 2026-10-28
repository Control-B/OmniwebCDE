"""Publishes verified builds to the preview server and runs generated APIs in the sandbox.

Layout under the builder data directory:
- previews/<token>/<sha>/{web,mobile}/   static bundles built in the sandbox
- previews/<token>/current               symlink to the published version
- runtime/<token>/<sha>/services/api     API source the preview process runs
- run/<token>/{api.sock,app.db,api.log}  mounted into the sandbox at /mnt/run

Generated APIs listen on a Unix socket only: the sandbox has no network, and the preview server
proxies `<preview>/api/*` to that socket.
"""

import asyncio
import logging
import os
import secrets
import shutil
import signal
from pathlib import Path

from ..config import Settings
from . import sandbox, toolchain

logger = logging.getLogger("omniweb.preview")
_processes: dict[str, asyncio.subprocess.Process] = {}
_locks: dict[str, asyncio.Lock] = {}
KEEP_VERSIONS = 3


def new_token() -> str:
    return secrets.token_hex(8)


def previews_root(settings: Settings) -> Path:
    return toolchain.data_dir(settings) / "previews"


def run_dir(settings: Settings, token: str) -> Path:
    return toolchain.data_dir(settings) / "run" / token


def url_for(settings: Settings, token: str) -> str:
    base = settings.preview_url.rstrip("/")
    scheme, _, host = base.partition("://")
    return f"{scheme}://{token}.preview.{host}/" if settings.preview_subdomains else f"{base}/p/{token}/"


def current(settings: Settings, token: str) -> Path | None:
    link = previews_root(settings) / token / "current"
    return link.resolve() if link.exists() else None


def _prune(directory: Path, keep: str) -> None:
    versions = sorted((p for p in directory.iterdir() if p.is_dir() and not p.is_symlink() and p.name != keep), key=lambda p: p.stat().st_mtime)
    for old in versions[: max(0, len(versions) - (KEEP_VERSIONS - 1))]:
        shutil.rmtree(old, ignore_errors=True)


async def publish(settings: Settings, token: str, sha: str, build_root: Path, targets: list[str]) -> dict:
    """Swaps the preview to a new verified build and (re)starts its API process."""
    target = previews_root(settings) / token / sha
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for kind in ("web", "mobile"):
        built = build_root / ".preview" / kind
        if built.is_dir():
            shutil.copytree(built, target / kind)
    link = previews_root(settings) / token / "current"
    temp = link.with_name("current.tmp")
    temp.unlink(missing_ok=True)
    temp.symlink_to(sha)
    os.replace(temp, link)
    _prune(target.parent, sha)
    api = None
    if "api" in targets and (build_root / "services/api/app/main.py").exists():
        runtime = toolchain.data_dir(settings) / "runtime" / token / sha
        shutil.rmtree(runtime, ignore_errors=True)
        shutil.copytree(build_root / "services/api", runtime / "services/api", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "tests"))
        _prune(runtime.parent, sha)
        api = await start_api(settings, token, runtime)
    return {"url": url_for(settings, token), "sha": sha, "web": (target / "web").is_dir(), "mobile": (target / "mobile").is_dir(), "api": api}


def _secret(settings: Settings, token: str) -> str:
    path = toolchain.data_dir(settings) / "runtime" / token / "secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()


async def start_api(settings: Settings, token: str, runtime: Path) -> dict:
    lock = _locks.setdefault(token, asyncio.Lock())
    async with lock:
        await stop_api(token)
        run = run_dir(settings, token)
        run.mkdir(parents=True, exist_ok=True)
        _kill_stale(run)
        (run / "api.sock").unlink(missing_ok=True)
        log = run / "api.log"
        if log.exists() and log.stat().st_size > 2_000_000:
            log.unlink()
        secret = _secret(settings, token)
        script = "cd services/api && python3 -m alembic upgrade head && exec python3 -m uvicorn app.main:app --uds /mnt/run/api.sock --no-access-log --log-level warning"
        job = sandbox.Job(
            command=["sh", "-c", script],
            app_dir=runtime,
            run_dir=run,
            env={"DATABASE_URL": "sqlite:////mnt/run/app.db", "SECRET_KEY": secret, "APP_ENV": "preview", "CORS_ORIGINS": ""},
            secrets=[secret],
        )
        tc = await toolchain.ensure(settings)
        try:
            process = await sandbox.spawn(settings, job, tc, log)
        except sandbox.SandboxUnavailable as exc:
            return {"running": False, "error": str(exc)}
        _processes[token] = process
        (run.parent / f"{token}.pid").write_text(str(process.pid))
        for _ in range(100):
            if (run / "api.sock").exists():
                return {"running": True}
            if process.returncode is not None:
                break
            await asyncio.sleep(0.1)
        tail = sandbox.redact(log.read_text(errors="replace")[-2000:], [secret]) if log.exists() else ""
        return {"running": process.returncode is None and (run / "api.sock").exists(), "error": tail or "The API did not start"}


def _kill_stale(run: Path) -> None:
    """Stops an API process left behind by a previous control-plane process."""
    pidfile = run.parent / f"{run.name}.pid"
    try:
        pid = int(pidfile.read_text())
        if Path(f"/proc/{pid}/cmdline").read_bytes().startswith(b"unshare"):
            os.killpg(pid, signal.SIGKILL)
    except (OSError, ValueError):
        pass
    pidfile.unlink(missing_ok=True)


async def stop_api(token: str) -> None:
    process = _processes.pop(token, None)
    if process and process.returncode is None:
        sandbox.kill(process)
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            logger.warning("preview api for %s did not exit", token)


def api_status(settings: Settings, token: str) -> dict:
    process = _processes.get(token)
    running = bool(process and process.returncode is None and (run_dir(settings, token) / "api.sock").exists())
    return {"running": running}


async def restore(settings: Settings, token: str) -> None:
    """Restarts the API for the published version after a control-plane restart."""
    published = current(settings, token)
    if not published:
        return
    runtime = toolchain.data_dir(settings) / "runtime" / token / published.name
    if (runtime / "services/api/app/main.py").exists():
        await start_api(settings, token, runtime)


async def reset_data(settings: Settings, token: str) -> None:
    (run_dir(settings, token) / "app.db").unlink(missing_ok=True)
    await restore(settings, token)


async def remove(settings: Settings, token: str) -> None:
    await stop_api(token)
    for base in ("previews", "runtime", "run"):
        shutil.rmtree(toolchain.data_dir(settings) / base / token, ignore_errors=True)


async def stop_all() -> None:
    for token in list(_processes):
        await stop_api(token)
