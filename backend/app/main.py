from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import SecurityHeadersMiddleware, TraceMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_auth_secret_for_env()
    settings.validate_cors_origins_for_env()
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


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
