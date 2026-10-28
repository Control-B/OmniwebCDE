"""Per-project source repository.

Each project's code lives in its own git repository under the builder data directory. The
generator records the hash of every file it writes in `.omniweb/manifest.json`; on later renders
it only rewrites files whose content still matches that hash, so changes a person made by hand
(in the editor, a cloud workspace, or GitHub) are never overwritten.

Git always runs with hooks disabled, signing off, no system or user configuration, and no
credentials in the environment. Generated code never executes against this directory: builds
run on an exported copy inside the sandbox.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..config import Settings
from .toolchain import data_dir

MANIFEST = ".omniweb/manifest.json"
MAX_FILE_BYTES = 512_000
EXCLUDED_EXPORT = {".git", "node_modules", ".preview", "__pycache__", ".pytest_cache", "dist"}
PROTECTED = re.compile(r"^(\.git/|\.git$|\.omniweb/)")
SAFE_PATH = re.compile(r"^[A-Za-z0-9_.@/ -]+$")
AUTHORS = {"agent": ("Omniweb agent", "agent@omniweb.local"), "user": ("Omniweb user", "user@omniweb.local")}


class StoreError(ValueError):
    pass


@dataclass
class ApplyResult:
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)


def sha256(content: str | bytes) -> str:
    data = content.encode() if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def clean_path(path: str) -> str:
    """Validates a repository-relative path supplied by a person or a model."""
    if not path or len(path) > 300 or "\\" in path or "\x00" in path or not SAFE_PATH.match(path):
        raise StoreError("Use a relative path with letters, digits, dots, dashes, underscores, and slashes")
    posix = PurePosixPath(path)
    if posix.is_absolute() or any(part in {"..", "."} for part in posix.parts):
        raise StoreError("Paths must stay inside the project")
    normalized = str(posix)
    if PROTECTED.match(normalized) or "node_modules" in posix.parts:
        raise StoreError("That path is managed by Omniweb")
    return normalized


class ProjectStore:
    def __init__(self, settings: Settings, project_id: uuid.UUID | str):
        self.root = data_dir(settings) / "projects" / str(project_id)
        self.repo = self.root / "repo"
        self._home = data_dir(settings) / "git-home"

    # -- git plumbing -------------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        self._home.mkdir(parents=True, exist_ok=True)
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self._home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "LANG": "C.UTF-8",
        }

    async def git(self, *args: str, check: bool = True, env: dict[str, str] | None = None, input_: bytes | None = None) -> str:
        argv = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "core.quotepath=off", "-c", "protocol.file.allow=always", *args]
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.repo,
            env={**self._env(), **(env or {})},
            stdin=asyncio.subprocess.PIPE if input_ is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate(input_)
        if check and process.returncode != 0:
            raise StoreError(err.decode(errors="replace").strip()[-800:] or f"git {args[0]} failed")
        return out.decode(errors="replace")

    async def git_status(self, *args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
        argv = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", *args]
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=self.repo, env={**self._env(), **(env or {})}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL
        )
        out, _ = await process.communicate()
        return process.returncode or 0, out.decode(errors="replace")

    @property
    def exists(self) -> bool:
        return (self.repo / ".git").is_dir()

    async def init(self, branch: str = "main") -> None:
        if self.exists:
            return
        self.repo.mkdir(parents=True, exist_ok=True)
        await self.git("init", "-q", "-b", branch)

    async def head(self) -> str | None:
        code, out = await self.git_status("rev-parse", "--verify", "-q", "HEAD")
        return out.strip() if code == 0 else None

    async def commit(self, message: str, author: str = "agent") -> str | None:
        """Commits everything in the worktree. Returns the new sha, or None when nothing changed."""
        await self.git("add", "-A")
        code, _ = await self.git_status("diff", "--cached", "--quiet")
        if code == 0 and await self.head():
            return None
        name, email = AUTHORS.get(author, AUTHORS["user"])
        identity = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": "Omniweb", "GIT_COMMITTER_EMAIL": "builder@omniweb.local"}
        await self.git("commit", "-q", "--allow-empty", "-m", message[:300], env=identity)
        return await self.head()

    # -- manifest-aware writes ----------------------------------------------------------------

    def manifest(self) -> dict[str, str]:
        path = self.repo / MANIFEST
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    def _write_manifest(self, manifest: dict[str, str]) -> None:
        path = self.repo / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(manifest.items())), indent=1) + "\n")

    def _current_hash(self, path: str) -> str | None:
        target = self.repo / path
        if target.is_symlink() or not target.is_file():
            return None
        return sha256(target.read_bytes())

    def user_modified(self) -> list[str]:
        """Generated files whose content no longer matches what the generator wrote."""
        return sorted(p for p, h in self.manifest().items() if self._current_hash(p) not in (h, None))

    def apply(self, files: dict[str, str], force: set[str] | None = None) -> ApplyResult:
        """Writes rendered files, keeping any file a person changed since the generator last wrote it."""
        force = force or set()
        manifest = self.manifest()
        result = ApplyResult()
        for path, content in files.items():
            path = clean_path(path)
            target = self.repo / path
            recorded = manifest.get(path)
            current = self._current_hash(path)
            if path not in force:
                if recorded is not None and current is not None and current != recorded:
                    result.preserved.append(path)
                    continue
                if recorded is None and current is not None and current != sha256(content):
                    result.preserved.append(path)
                    continue
                if recorded is not None and current is None and not target.exists():
                    # Deleted by a person after generation; respect the deletion.
                    result.preserved.append(path)
                    continue
            if current != sha256(content):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                result.written.append(path)
            manifest[path] = sha256(content)
        for path in [p for p in manifest if p not in files]:
            current = self._current_hash(path)
            if current == manifest[path]:
                (self.repo / path).unlink()
                result.deleted.append(path)
                del manifest[path]
            elif current is None:
                del manifest[path]
            else:
                result.preserved.append(path)
                del manifest[path]
        self._write_manifest(manifest)
        return result

    def write(self, path: str, content: str) -> str:
        """A person's edit. Generated files they change become theirs (the manifest hash no longer matches)."""
        path = clean_path(path)
        if len(content.encode()) > MAX_FILE_BYTES:
            raise StoreError("Files are limited to 500 KB in the editor")
        target = self.repo / path
        if target.is_symlink():
            raise StoreError("Symbolic links cannot be edited")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return path

    def delete(self, path: str) -> None:
        path = clean_path(path)
        target = self.repo / path
        if not target.is_file() or target.is_symlink():
            raise StoreError("File not found")
        target.unlink()

    def adopt(self, path: str) -> None:
        """Marks a file as generator-owned again, e.g. after an agent edits it at a person's request."""
        manifest = self.manifest()
        current = self._current_hash(path)
        if current:
            manifest[path] = current
            self._write_manifest(manifest)

    # -- reads --------------------------------------------------------------------------------

    async def tree(self, sha: str | None = None) -> list[dict]:
        if not await self.head():
            return []
        modified = set(self.user_modified())
        generated = self.manifest()
        out = await self.git("ls-tree", "-r", "-l", "--full-tree", sha or "HEAD")
        files = []
        for line in out.splitlines():
            meta, path = line.split("\t", 1)
            _, kind, _, size = meta.split()
            if kind != "blob" or path.startswith(".omniweb/"):
                continue
            files.append({"path": path, "size": int(size) if size.isdigit() else 0, "generated": path in generated, "modified": path in modified})
        return files

    def working_files(self) -> list[str]:
        files = []
        for base, dirs, names in os.walk(self.repo):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_EXPORT and not (base == str(self.repo) and d == ".omniweb")]
            for name in names:
                files.append(str(Path(base, name).relative_to(self.repo)))
        return sorted(files)

    def read(self, path: str) -> str:
        path = clean_path(path)
        target = self.repo / path
        if target.is_symlink() or not target.is_file():
            raise StoreError("File not found")
        data = target.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise StoreError("File is too large to open")
        try:
            return data.decode()
        except UnicodeDecodeError as exc:
            raise StoreError("Binary files cannot be opened in the editor") from exc

    async def read_at(self, sha: str, path: str) -> str | None:
        code, out = await self.git_status("show", f"{sha}:{clean_path(path)}")
        return out if code == 0 else None

    async def log(self, limit: int = 100) -> list[dict]:
        if not await self.head():
            return []
        out = await self.git("log", f"-{limit}", "--format=%H%x1f%P%x1f%an%x1f%aI%x1f%s")
        rows = []
        for line in out.splitlines():
            sha, parents, author, date, subject = line.split("\x1f")
            rows.append({"sha": sha, "parent": parents.split(" ")[0] if parents else None, "author": author, "date": date, "message": subject})
        return rows

    async def diff(self, sha: str, base: str | None = None, max_bytes: int = 200_000) -> dict:
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha) or (base and not re.fullmatch(r"[0-9a-f]{7,40}", base)):
            raise StoreError("Unknown checkpoint")
        if base is None:
            code, parent = await self.git_status("rev-parse", "--verify", "-q", f"{sha}^")
            base = parent.strip() if code == 0 else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        stat = await self.git("diff", "--numstat", base, sha, "--", ".", ":(exclude).omniweb")
        files = []
        for line in stat.splitlines():
            added, removed, path = line.split("\t", 2)
            files.append({"path": path, "added": int(added) if added.isdigit() else 0, "removed": int(removed) if removed.isdigit() else 0})
        patch = await self.git("diff", "--no-color", "-U3", base, sha, "--", ".", ":(exclude).omniweb")
        truncated = len(patch) > max_bytes
        return {"sha": sha, "base": base, "files": files, "patch": patch[:max_bytes], "truncated": truncated}

    async def dirty(self) -> list[str]:
        out = await self.git("status", "--porcelain", "--untracked-files=all")
        return [line[3:] for line in out.splitlines() if not line[3:].startswith(".omniweb/")]

    async def checkout_tree(self, sha: str) -> None:
        """Makes the worktree (including the manifest) match a past commit, without moving history."""
        await self.git("rm", "-r", "-q", "--cached", "--ignore-unmatch", ".")
        for path in self.working_files():
            (self.repo / path).unlink()
        (self.repo / MANIFEST).unlink(missing_ok=True)
        await self.git("checkout", sha, "--", ".")

    # -- export -------------------------------------------------------------------------------

    def export(self, destination: Path) -> Path:
        shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)

        def ignore(directory: str, names: list[str]) -> set[str]:
            skip = {n for n in names if n in EXCLUDED_EXPORT}
            if Path(directory) == self.repo:
                skip.add(".omniweb")
            return skip | {n for n in names if (Path(directory) / n).is_symlink()}

        shutil.copytree(self.repo, destination, ignore=ignore)
        return destination

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
