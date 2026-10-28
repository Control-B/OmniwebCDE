"""Tenant-scoped, content-addressed local asset storage.

Production can replace this adapter with object storage without changing asset records. Paths
are derived from tenant and SHA-256 only; user filenames never become filesystem paths.
"""

import hashlib
from pathlib import Path

from ..config import Settings


class AssetStore:
    def __init__(self, settings: Settings):
        self.root = Path(settings.asset_data_dir).resolve()

    def put(self, tenant_id, data: bytes, extension: str = "bin") -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        extension = extension.lower().removeprefix(".")
        if extension not in {"bin", "png", "jpg", "jpeg", "webp", "mp4"}:
            extension = "bin"
        target = self.root / str(tenant_id) / digest[:2] / f"{digest}.{extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        return f"local://{tenant_id}/{digest[:2]}/{digest}.{extension}", digest

    def read(self, tenant_id, location: str) -> bytes:
        prefix = f"local://{tenant_id}/"
        if not location.startswith(prefix):
            raise FileNotFoundError("Asset is outside this tenant")
        relative = location.removeprefix(prefix)
        target = (self.root / str(tenant_id) / relative).resolve()
        tenant_root = (self.root / str(tenant_id)).resolve()
        if tenant_root not in target.parents:
            raise FileNotFoundError("Invalid asset path")
        return target.read_bytes()
