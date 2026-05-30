"""FastAPI app factory + dynamic router generation for SID consumers."""

from __future__ import annotations

import inspect
import json
import typing
from typing import TYPE_CHECKING, Callable

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .api import EndpointMeta
from .dicts import AsyncBeaverDict
from .lists import AsyncBeaverList
from .queues import AsyncBeaverQueue
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


def _coerce_path_params(method: Callable, params: dict) -> dict:
    """Cast URL path params to the types declared in the method signature.

    Handles bare `int` / `float` annotations and `Union[int, ...]` shapes
    (e.g. `Union[int, slice]` — over-the-wire we only support int).
    """
    sig = inspect.signature(method)
    out = {}
    for k, v in params.items():
        param = sig.parameters.get(k)
        if param is None or param.annotation is inspect.Parameter.empty:
            out[k] = v
            continue
        ann = param.annotation
        candidates = typing.get_args(ann) or (ann,)
        if int in candidates:
            out[k] = int(v)
        elif float in candidates:
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _jsonify_result(result):
    """Return a JSON-serializable representation. NamedTuples → dict."""
    if result is None:
        return None
    if isinstance(result, tuple) and hasattr(result, "_asdict"):
        return result._asdict()
    return result


def _router_for_manager(manager_cls, db_accessor: Callable) -> APIRouter:
    """Walk @expose'd methods on manager_cls; mount each as a route.

    `db_accessor(db, name)` returns a fresh manager instance bound to that name.
    """
    router = APIRouter()

    for method_name in dir(manager_cls):
        method = getattr(manager_cls, method_name, None)
        meta: EndpointMeta | None = getattr(method, "__beaver_endpoint__", None)
        if meta is None:
            continue

        async def _handler(
            request: Request, _mn=method_name, _meta=meta, _method=method
        ):
            db = request.app.state.beaver_db
            path_params = dict(request.path_params)
            name = path_params.pop("name")
            path_params = _coerce_path_params(_method, path_params)
            manager = db_accessor(db, name)
            kwargs = dict(path_params)

            if _meta.method in ("PUT", "POST"):
                raw = await request.body()
                if raw:
                    body = json.loads(raw)
                    if isinstance(body, dict):
                        for k, v in body.items():
                            kwargs[k] = v
            elif _meta.method == "GET":
                for k, v in request.query_params.items():
                    kwargs[k] = json.loads(v)

            target = getattr(manager, _mn)
            result = await target(**kwargs)
            return _jsonify_result(result)

        full_path = "/{name}" + meta.path
        router.add_api_route(
            full_path,
            _handler,
            methods=[meta.method],
            name=f"{manager_cls.__name__}_{method_name}",
        )

    return router


def create_app(db: "AsyncBeaverDB", *, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="beaver", version=__version__)
    app.state.beaver_db = db
    if api_key:
        app.add_middleware(BearerAuthMiddleware, expected=api_key)
    app.add_exception_handler(Exception, _to_error_envelope)
    app.include_router(
        _router_for_manager(AsyncBeaverDict, lambda db, name: db.dict(name)),
        prefix="/dicts",
        tags=["dicts"],
    )
    app.include_router(
        _router_for_manager(AsyncBeaverList, lambda db, name: db.list(name)),
        prefix="/lists",
        tags=["lists"],
    )
    app.include_router(
        _router_for_manager(AsyncBeaverQueue, lambda db, name: db.queue(name)),
        prefix="/queues",
        tags=["queues"],
    )
    return app
