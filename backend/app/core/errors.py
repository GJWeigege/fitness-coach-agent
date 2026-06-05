import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

PUBLIC_ERROR_MESSAGE = "处理请求时发生错误，请稍后重试。"

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            detail = exc.detail if isinstance(exc.detail, str) else PUBLIC_ERROR_MESSAGE
            return JSONResponse(status_code=exc.status_code, content={"detail": detail})
        logger.exception("unhandled_exception path=%s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": PUBLIC_ERROR_MESSAGE})
