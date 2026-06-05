import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.api.observability import router as observability_router
from app.api.profile import router as profile_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import SecurityHeadersMiddleware, TraceMiddleware
from app.db.seed_graph import seed_demo_graph
from app.db.seed_knowledge import seed_demo_knowledge
from app.db.seed_users import seed_demo_users
from app.db.session import AsyncSessionLocal

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_auth_secret_for_env()
    settings.validate_cors_origins_for_env()

    if settings.app_env in ("dev", "test"):
        async with AsyncSessionLocal() as db:
            seeded_users = await seed_demo_users(db)
            await db.commit()
            if seeded_users:
                logger.info("seeded demo users: %s", ", ".join(seeded_users))

        async with AsyncSessionLocal() as db:
            seeded_docs = await seed_demo_knowledge(db)
            await db.commit()
            if seeded_docs:
                logger.info("seeded %s knowledge documents", seeded_docs)

        async with AsyncSessionLocal() as db:
            seeded_graph = await seed_demo_graph(db)
            await db.commit()
            if seeded_graph:
                logger.info("seeded %s graph entities/edges", seeded_graph)

    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
register_exception_handlers(app)
app.add_middleware(TraceMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(observability_router)
app.include_router(profile_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
