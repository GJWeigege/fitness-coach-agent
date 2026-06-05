# Test database must exist before running pytest:
#   CREATE DATABASE fitness_coach_test;
# (PostgreSQL does not auto-create it; use the same host/credentials as TEST_DATABASE_URL.)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 — register all ORM tables on Base.metadata
from app.core.deps import get_db
from app.core.login_lockout import login_lockout
from app.core.rate_limit import reset_rate_limiter_for_tests
from app.db.models import Base
from app.main import app

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/fitness_coach_test"


@pytest.fixture(autouse=True)
def reset_auth_guards():
    reset_rate_limiter_for_tests()
    login_lockout.reset_for_tests()
    yield
    reset_rate_limiter_for_tests()
    login_lockout.reset_for_tests()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
