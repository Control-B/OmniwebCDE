"""Runs generated application code in isolation.

Generated code is untrusted. Every build, test, and preview process runs through this module:

- namespace (development): Linux user, mount, PID, and network namespaces. The process sees its
  own build directory, the read-only toolchain, and nothing from the host's home, workspace,
  temporary, or runtime directories. It has no network access and a cleared environment.
- container (production): a locked-down container per run (no network, read-only root, all
  capabilities dropped, memory and PID limits). Use a runtime such as gVisor for kernel isolation.
- disabled: generation still renders code, but nothing is executed.
"""

import asyncio
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from .toolchain import data_dir

HIDDEN = ["/home", "/root", "/run", "/var/run", "/tmp", "/var/tmp", "/workspace", "/cursor", "/opt", "/exec-daemon", "/srv", "/var/lib", "/var/log", "/media"]  # noqa: S108  guest paths inside the sandbox
SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|dop_v1_[a-f0-9]{20,}"
    r"|Bearer\s+[A-Za-z0-9._-]{16,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
MAX_OUTPUT = 60_000
SCRIPT = """set -eu
mount -t tmpfs -o size=8m,mode=755 tmpfs /mnt
mkdir -p /mnt/app /mnt/toolchain /mnt/run
mount --bind "$OW_APP" /mnt/app
mount --bind "$OW_TOOLCHAIN" /mnt/toolchain
mount -o remount,bind,ro /mnt/toolchain
if [ -n "${OW_RUN:-}" ]; then mount --bind "$OW_RUN" /mnt/run; fi
for d in $OW_HIDE; do if [ -d "$d" ]; then mount -t tmpfs -o size=1g,mode=1777 tmpfs "$d"; fi; done
cd /mnt/app
exec "$@"
"""
GUEST_PATH = "/mnt/toolchain/bin:/usr/local/bin:/usr/bin:/bin"


class SandboxUnavailable(RuntimeError):
    pass


@dataclass
class SandboxResult:
    exit_code: int
    output: str
    duration: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class Job:
    command: list[str]
    app_dir: Path
    run_dir: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)
    timeout: float | None = None


def redact(text: str, secrets: list[str] | None = None) -> str:
    for secret in secrets or []:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "[redacted]")
    return SECRET_PATTERN.sub("[redacted]", text)


def link_node_modules(app_dir: Path, toolchain: Path) -> None:
    """Creates a writable node_modules whose entries point at the read-only toolchain packages."""
    target = app_dir / "node_modules"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for entry in (toolchain / "node_modules").iterdir():
        if entry.name.startswith("."):
            continue
        (target / entry.name).symlink_to(f"/mnt/toolchain/node_modules/{entry.name}")
    for stub in (toolchain / "stubs").iterdir():
        if not (target / stub.name).exists():
            (target / stub.name).symlink_to(f"/mnt/toolchain/stubs/{stub.name}")


def guest_env(job: Job) -> dict[str, str]:
    return {
        "PATH": GUEST_PATH,
        "HOME": "/tmp",  # noqa: S108  guest paths inside the sandbox
        "LANG": "C.UTF-8",
        "PYTHONPATH": "/mnt/toolchain/python",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CI": "1",
        "NO_COLOR": "1",
        **job.env,
    }


def _namespace_argv(settings: Settings, job: Job, toolchain: Path) -> tuple[list[str], dict[str, str]]:
    hidden = HIDDEN + [str(data_dir(settings))]
    limits = ["/usr/bin/prlimit", "--cpu=900", "--fsize=1073741824", "--nofile=4096", "--core=0", "--"]
    inner = ["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in guest_env(job).items()], *limits, *job.command]
    argv = ["unshare", "--user", "--map-root-user", "--mount", "--pid", "--fork", "--kill-child", "--mount-proc", "--net", "--ipc", "--uts", "sh", "-c", SCRIPT, "sandbox", *inner]
    host_env = {
        "PATH": "/usr/bin:/bin",
        "OW_APP": str(job.app_dir),
        "OW_TOOLCHAIN": str(toolchain),
        "OW_RUN": str(job.run_dir or ""),
        "OW_HIDE": " ".join(hidden),
    }
    return argv, host_env


def _container_argv(settings: Settings, job: Job, toolchain: Path) -> tuple[list[str], dict[str, str]]:
    argv = [
        "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "512", "--memory", "2g", "--cpus", "2", "--user", "10001:10001", "--tmpfs", "/tmp:size=1g",  # noqa: S108  guest paths inside the sandbox
        "-v", f"{job.app_dir}:/mnt/app", "-v", f"{toolchain}:/mnt/toolchain:ro", "-w", "/mnt/app",
    ]
    if job.run_dir:
        argv += ["-v", f"{job.run_dir}:/mnt/run"]
    for key, value in guest_env(job).items():
        argv += ["-e", f"{key}={value}"]
    return [*argv, settings.sandbox_image, *job.command], {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def argv_for(settings: Settings, job: Job, toolchain: Path) -> tuple[list[str], dict[str, str]]:
    if settings.sandbox_mode == "disabled":
        raise SandboxUnavailable("Code execution is disabled (OMNIWEB_SANDBOX_MODE=disabled)")
    if settings.sandbox_mode == "container":
        if not shutil.which("docker"):
            raise SandboxUnavailable("OMNIWEB_SANDBOX_MODE=container needs a container runtime on the build host")
        return _container_argv(settings, job, toolchain)
    if not shutil.which("unshare"):
        raise SandboxUnavailable("Namespace sandboxing needs util-linux unshare")
    return _namespace_argv(settings, job, toolchain)


async def run(settings: Settings, job: Job, toolchain: Path) -> SandboxResult:
    argv, host_env = argv_for(settings, job, toolchain)
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *argv, env=host_env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL, start_new_session=True
    )
    chunks: list[bytes] = []
    size = 0

    async def pump() -> None:
        nonlocal size
        assert process.stdout
        while chunk := await process.stdout.read(8192):
            chunks.append(chunk)
            size += len(chunk)
            while size > MAX_OUTPUT * 2 and len(chunks) > 1:
                size -= len(chunks.pop(0))

    timed_out = False
    try:
        await asyncio.wait_for(asyncio.gather(pump(), process.wait()), timeout=job.timeout or settings.sandbox_timeout_seconds)
    except TimeoutError:
        timed_out = True
        kill(process)
        await process.wait()
    except asyncio.CancelledError:
        kill(process)
        raise
    output = b"".join(chunks).decode(errors="replace")[-MAX_OUTPUT:]
    return SandboxResult(process.returncode if process.returncode is not None else -1, redact(output, job.secrets), time.monotonic() - started, timed_out)


async def spawn(settings: Settings, job: Job, toolchain: Path, log_path: Path) -> asyncio.subprocess.Process:
    """Starts a long-running sandboxed process, such as a preview API server."""
    argv, host_env = argv_for(settings, job, toolchain)
    log = log_path.open("ab")
    try:
        return await asyncio.create_subprocess_exec(*argv, env=host_env, stdout=log, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL, start_new_session=True)
    finally:
        log.close()


def kill(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
