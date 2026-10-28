"""Installs the pinned, read-only toolchain that generated apps build against.

The toolchain is trusted code: its packages are pinned in toolchain/package.json and
toolchain/requirements.txt and installed without lifecycle scripts. Generated repositories never
run their own package installs, so a generated package.json cannot pull in arbitrary code.
"""

import asyncio
import hashlib
import logging
import os
import shutil
import sys
from pathlib import Path

from ..config import Settings

SOURCE = Path(__file__).parent / "toolchain"
logger = logging.getLogger("omniweb.builder")
_lock = asyncio.Lock()


def version() -> str:
    digest = hashlib.sha256()
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(SOURCE).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def data_dir(settings: Settings) -> Path:
    path = Path(settings.builder_data_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def toolchain_dir(settings: Settings) -> Path:
    base = Path(settings.builder_toolchain_dir).resolve() if settings.builder_toolchain_dir else data_dir(settings) / "toolchain"
    return base / version()


def node_binary() -> str:
    found = shutil.which("node")
    if not found:
        raise RuntimeError("Node.js is required to build generated apps")
    return str(Path(found).resolve())


async def _run(*args: str, cwd: Path) -> None:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"), "npm_config_update_notifier": "false"}  # noqa: S108
    process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output, _ = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"Toolchain step failed: {' '.join(args[:3])}\n{output.decode(errors='replace')[-2000:]}")


async def ensure(settings: Settings) -> Path:
    target = toolchain_dir(settings)
    if (target / ".ready").exists():
        return target
    async with _lock:
        if (target / ".ready").exists():
            return target
        logger.info("installing generated-app toolchain %s", target.name)
        partial = target.with_name(target.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        shutil.copy2(SOURCE / "package.json", partial / "package.json")
        shutil.copytree(SOURCE / "scripts", partial / "scripts")
        shutil.copytree(SOURCE / "stubs", partial / "stubs")
        await _run("npm", "install", "--ignore-scripts", "--no-audit", "--no-fund", "--loglevel=error", cwd=partial)
        (partial / "bin").mkdir()
        shutil.copy2(node_binary(), partial / "bin" / "node")
        await _run(
            sys.executable, "-m", "pip", "install", "--quiet", "--no-warn-script-location", "--disable-pip-version-check",
            "--break-system-packages", "--target", str(partial / "python"), "-r", str(SOURCE / "requirements.txt"), cwd=partial,
        )
        if target.exists():
            shutil.rmtree(target)
        partial.rename(target)
        (target / ".ready").write_text(version())
        return target


def is_ready(settings: Settings) -> bool:
    return (toolchain_dir(settings) / ".ready").exists()
