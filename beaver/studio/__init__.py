"""Local, read-only Beaver Studio web application."""

from __future__ import annotations

from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from beaver import __version__
from beaver.core import AsyncBeaverDB
from beaver.errors import envelope_from_exception, http_code_for
from beaver.inspection import AsyncBeaverInspector


_STATIC_DIR = Path(__file__).with_name("static")


def _error_response(exc: Exception, *, status_code: int | None = None) -> JSONResponse:
    envelope = envelope_from_exception(exc)
    return JSONResponse(
        status_code=status_code if status_code is not None else http_code_for(exc),
        content=envelope.model_dump(),
    )


async def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
    operations = getattr(request.app.state, "operations", None)
    if operations is not None:
        operations.append(
            {
                "timestamp": time.time(),
                "level": "error",
                "method": request.method,
                "path": request.url.path,
                "error": type(exc).__name__,
            }
        )
    return _error_response(exc)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(exc, status_code=422)


def create_studio_app(db_path: str | Path) -> FastAPI:
    """Create a local Studio app backed by a read-only Beaver connection."""

    path = str(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = AsyncBeaverDB(path, read_only=True)
        await db.connect()
        app.state.beaver_db = db
        app.state.beaver_inspector = AsyncBeaverInspector(db)
        try:
            yield
        finally:
            await db.close()

    app = FastAPI(
        title="Beaver Studio",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_exception)
    app.state.operations = deque(maxlen=200)

    @app.middleware("http")
    async def studio_headers(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if request.url.path != "/admin/v1/operations":
            request.app.state.operations.append(
                {
                    "timestamp": time.time(),
                    "level": "info",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/admin/v1/info")
    async def info(request: Request):
        return await request.app.state.beaver_inspector.info()

    @app.get("/admin/v1/catalog")
    async def catalog(request: Request, include_internal: bool = False):
        return await request.app.state.beaver_inspector.catalog(
            include_internal=include_internal
        )

    @app.get("/admin/v1/stores/{kind}/items")
    async def store_items(
        kind: str,
        request: Request,
        name: str,
        limit: int = Query(default=50),
        cursor: str | None = None,
        query: str | None = None,
        search: str | None = None,
        start: float | None = None,
        end: float | None = None,
        source: str | None = None,
        target: str | None = None,
        label: str | None = None,
    ):
        return await request.app.state.beaver_inspector.page(
            kind,
            name,
            limit=limit,
            cursor=cursor,
            query=query,
            search=search,
            start=start,
            end=end,
            source=source,
            target=target,
            label=label,
        )

    @app.get("/admin/v1/stores/{kind}/indexes")
    async def store_indexes(kind: str, request: Request, name: str):
        return await request.app.state.beaver_inspector.indexes(kind, name)

    @app.get("/admin/v1/stores/{kind}/item")
    async def store_item(
        kind: str,
        request: Request,
        name: str,
        item_id: str = Query(alias="id"),
        preview_bytes: int = Query(default=16 * 1024, ge=1, le=64 * 1024),
    ):
        return await request.app.state.beaver_inspector.detail(
            kind, name, item_id, preview_bytes=preview_bytes
        )

    @app.get("/admin/v1/schema")
    async def schema(request: Request):
        return await request.app.state.beaver_inspector.schema()

    @app.get("/admin/v1/diagnostics")
    async def diagnostics(request: Request):
        return await request.app.state.beaver_inspector.diagnostics()

    @app.get("/admin/v1/operations")
    async def operations(request: Request):
        return list(request.app.state.operations)

    app.mount("/assets", StaticFiles(directory=_STATIC_DIR), name="studio-assets")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(_STATIC_DIR / "index.html")

    return app


__all__ = ["create_studio_app"]
