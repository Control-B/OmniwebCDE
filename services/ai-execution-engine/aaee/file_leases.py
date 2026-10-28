"""File leases: two agents never modify overlapping paths of the same project at once."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import FileLease

ALL = "*"


class LeaseConflict(Exception):
    def __init__(self, path: str, holder: uuid.UUID):
        super().__init__(f"{path} is being modified by another task")
        self.path = path
        self.holder = holder


def overlaps(a: str, b: str) -> bool:
    if ALL in (a, b):
        return True
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


async def acquire(db: AsyncSession, tenant_id: uuid.UUID, resource: str, paths: list[str], execution_id: uuid.UUID, ttl_seconds: int) -> None:
    now = datetime.now(UTC)
    await db.execute(delete(FileLease).where(FileLease.expires_at < now))
    held = list(await db.scalars(select(FileLease).where(FileLease.tenant_id == tenant_id, FileLease.resource == resource)))
    wanted = paths or [ALL]
    for lease in held:
        if lease.execution_id == execution_id:
            continue
        for path in wanted:
            if overlaps(path, lease.path):
                raise LeaseConflict(path, lease.execution_id)
    for path in wanted:
        if not any(lease.execution_id == execution_id and lease.path == path for lease in held):
            db.add(FileLease(tenant_id=tenant_id, resource=resource, path=path, execution_id=execution_id, expires_at=now + timedelta(seconds=ttl_seconds)))
    await db.flush()


async def release(db: AsyncSession, execution_ids: list[uuid.UUID]) -> None:
    if execution_ids:
        await db.execute(delete(FileLease).where(FileLease.execution_id.in_(execution_ids)))
