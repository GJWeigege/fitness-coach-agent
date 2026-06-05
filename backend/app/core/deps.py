from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency; wired in T-004."""
    raise NotImplementedError("Database session not configured yet (T-004)")
