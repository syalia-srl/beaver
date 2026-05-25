"""FastAPI app factory + dynamic router generation for SID consumers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .dicts import AsyncBeaverDict
from .errors import ErrorEnvelope, envelope_from_exception, http_code_for

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


async def _to_error_envelope(request: Request, exc: Exception) -> JSONResponse:
    env = envelope_from_exception(exc)
    code = http_code_for(exc)
    return JSONResponse(status_code=code, content=env.model_dump())


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, expected: str):
        super().__init__(app)
        self._expected = expected

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {self._expected}":
            env = ErrorEnvelope(
                error="AuthError", message="invalid or missing bearer token"
            )
            return JSONResponse(status_code=401, content=env.model_dump())
        return await call_next(request)


def _router_for_dicts(db: "AsyncBeaverDB") -> APIRouter:
    """Build a FastAPI router by introspecting AsyncBeaverDict for @expose'd methods."""
    router = APIRouter()

    for method_name in dir(AsyncBeaverDict):
        method = getattr(AsyncBeaverDict, method_name, None)
        meta = getattr(method, "__beaver_endpoint__", None)
        if meta is None:
            continue

        async def _handler(request: Request, _mn=method_name, _meta=meta):
            path_params = dict(request.path_params)
            name = path_params.pop("name")
            manager = db.dict(name)
            kwargs = dict(path_params)
            if _meta.method in ("PUT", "POST") and _meta.body_param:
                body = await request.json()
                kwargs[_meta.body_param] = body.get(_meta.body_param)
                for k, v in body.items():
                    if k != _meta.body_param:
                        kwargs[k] = v
            elif _meta.method == "GET":
                for k, v in request.query_params.items():
                    kwargs[k] = json.loads(v)
            target = getattr(manager, _mn)
            result = await target(**kwargs)
            return result

        full_path = "/{name}" + meta.path
        router.add_api_route(
            full_path,
            _handler,
            methods=[meta.method],
            name=f"dict_{method_name}",
        )

    return router


def create_app(db: "AsyncBeaverDB", *, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="beaver", version=__version__)
    if api_key:
        app.add_middleware(BearerAuthMiddleware, expected=api_key)
    app.add_exception_handler(Exception, _to_error_envelope)
    app.include_router(_router_for_dicts(db), prefix="/dicts", tags=["dicts"])
    return app
