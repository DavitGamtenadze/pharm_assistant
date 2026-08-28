"""FastAPI application entry point."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pharm_assistant import __version__
from pharm_assistant.api.routes import api_router, health_router
from pharm_assistant.container import get_container
from pharm_assistant.core.config import get_settings
from pharm_assistant.core.logging import (
    bind_request_id,
    clear_request_context,
    configure_logging,
    get_logger,
)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    services = get_container()
    yield
    await services.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json_logs=settings.env == "production")
    public_docs = None if settings.env == "production" else "/api/docs"
    app = FastAPI(
        title=settings.app_name,
        description="Citation-grounded question answering over medical PDFs.",
        version=__version__,
        docs_url=public_docs,
        redoc_url=None,
        openapi_url=None if settings.env == "production" else "/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    )
    app.include_router(health_router)
    app.include_router(api_router)

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else uuid.uuid4().hex
        bind_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            if not request.url.path.endswith("/file"):
                response.headers["X-Frame-Options"] = "DENY"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            if settings.env == "production":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
            get_logger().info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
            return response
        finally:
            clear_request_context()

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
        get_logger().exception(
            "unhandled_error",
            method=request.method,
            path=request.url.path,
            error_type=type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred."},
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "docs": "/api/docs",
            "health": "/health",
        }

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "pharm_assistant.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env == "development",
    )


if __name__ == "__main__":
    run()
