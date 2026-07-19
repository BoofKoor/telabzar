"""عملیاتِ سادهٔ پایگاه‌داده."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import File


async def get_file_by_ref(session: AsyncSession, ref: str) -> File | None:
    result = await session.execute(select(File).where(File.ref == ref))
    return result.scalar_one_or_none()
