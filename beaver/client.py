"""AsyncBeaverClient + RemoteDict — remote dispatch via httpx, hand-written wrappers."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable, ClassVar

import httpx

from .api import EndpointMeta
from .dicts import AsyncBeaverDict
from .errors import ErrorEnvelope, LocalOnlyError, raise_from_envelope


def _build_remote_dispatchers(manager_cls) -> dict[str, Callable]:
    """For each @expose'd method on manager_cls, build a remote dispatcher.

    Each dispatcher signature: (http: httpx.AsyncClient, name: str, **kwargs) -> Any
    """
    dispatchers: dict[str, Callable] = {}

    for method_name in dir(manager_cls):
        method = getattr(manager_cls, method_name, None)
        meta: EndpointMeta | None = getattr(method, "__beaver_endpoint__", None)
        if meta is None:
            continue

        async def _dispatch(http, name, _meta=meta, **kwargs):
            path = "/{name}" + _meta.path
            format_kwargs = {"name": name}
            for k in list(kwargs.keys()):
                placeholder = "{" + k + "}"
                if placeholder in path:
                    format_kwargs[k] = kwargs.pop(k)
            url = "/dicts" + path.format(**format_kwargs)

            if _meta.method == "GET":
                params = {k: json.dumps(v) for k, v in kwargs.items()}
                response = await http.request("GET", url, params=params)
            elif _meta.method == "DELETE":
                response = await http.request("DELETE", url)
            else:
                response = await http.request(_meta.method, url, json=kwargs)

            if response.status_code >= 400:
                env = ErrorEnvelope.model_validate(response.json())
                raise_from_envelope(env)
            if response.content:
                return response.json()
            return None

        dispatchers[method_name] = _dispatch

    return dispatchers


class RemoteDict:
    """Remote proxy for AsyncBeaverDict.

    Hand-written wrappers around _BUILDERS keep the class IDE-introspectable.
    Local-only methods (keys/values/items/dump/load/batched) raise LocalOnlyError.
    """

    _BUILDERS: ClassVar[dict[str, Callable]] = _build_remote_dispatchers(
        AsyncBeaverDict
    )

    def __init__(self, http: httpx.AsyncClient, name: str, model=None):
        self._http = http
        self._name = name
        self._model = model

    # --- @expose'd methods ---

    async def set(self, key: str, value, ttl_seconds: float | None = None):
        return await self._BUILDERS["set"](
            self._http, self._name, key=key, value=value, ttl_seconds=ttl_seconds
        )

    async def get(self, key: str):
        return await self._BUILDERS["get"](self._http, self._name, key=key)

    async def delete(self, key: str):
        return await self._BUILDERS["delete"](self._http, self._name, key=key)

    async def fetch(self, key: str, default=None):
        return await self._BUILDERS["fetch"](
            self._http, self._name, key=key, default=default
        )

    async def pop(self, key: str, default=None):
        return await self._BUILDERS["pop"](
            self._http, self._name, key=key, default=default
        )

    async def count(self) -> int:
        return await self._BUILDERS["count"](self._http, self._name)

    async def contains(self, key: str) -> bool:
        return await self._BUILDERS["contains"](self._http, self._name, key=key)

    async def clear(self):
        return await self._BUILDERS["clear"](self._http, self._name)

    # --- @local_only methods ---

    async def keys(self):
        raise LocalOnlyError(AsyncBeaverDict.keys.__beaver_local_only__)
        yield  # noqa: makes this an async generator so `async for` syntax works

    async def values(self):
        raise LocalOnlyError(AsyncBeaverDict.values.__beaver_local_only__)
        yield  # noqa

    async def items(self):
        raise LocalOnlyError(AsyncBeaverDict.items.__beaver_local_only__)
        yield  # noqa

    async def dump(self, *args, **kwargs):
        raise LocalOnlyError(AsyncBeaverDict.dump.__beaver_local_only__)

    async def load(self, *args, **kwargs):
        raise LocalOnlyError(AsyncBeaverDict.load.__beaver_local_only__)

    def batched(self):
        raise LocalOnlyError(AsyncBeaverDict.batched.__beaver_local_only__)


class AsyncBeaverClient:
    """Remote-DB equivalent of AsyncBeaverDB. Use beaver.connect(url) instead of instantiating directly."""

    def __init__(self, base_url: str, api_key: str | None = None):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0)

    def dict(self, name: str, model=None) -> RemoteDict:
        return RemoteDict(self._http, name, model)

    async def close(self):
        await self._http.aclose()


class BeaverClient:
    """Sync portal over AsyncBeaverClient — mirrors BeaverDB's reactor-thread pattern."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="BeaverClient-Reactor"
        )
        self._thread.start()

        async def init():
            return AsyncBeaverClient(base_url, api_key=api_key)

        future = asyncio.run_coroutine_threadsafe(init(), self._loop)
        self._async = future.result()
        self._closed = False

    def close(self):
        if self._closed:
            return

        async def shutdown():
            await self._async.close()

        future = asyncio.run_coroutine_threadsafe(shutdown(), self._loop)
        future.result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1.0)
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def dict(self, name: str, model=None):
        from .bridge import BeaverBridge

        async def factory():
            return self._async.dict(name, model)

        future = asyncio.run_coroutine_threadsafe(factory(), self._loop)
        return BeaverBridge(future.result(), self._loop)
