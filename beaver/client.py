"""AsyncBeaverClient + Remote* proxies — remote dispatch via httpx, hand-written wrappers."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable, ClassVar

import httpx

from .api import EndpointMeta
from .dicts import AsyncBeaverDict
from .lists import AsyncBeaverList
from .queues import AsyncBeaverQueue
from .errors import ErrorEnvelope, LocalOnlyError, raise_from_envelope


def _build_remote_dispatchers(manager_cls, mount_prefix: str) -> dict[str, Callable]:
    """For each @expose'd method on manager_cls, build a remote dispatcher.

    Each dispatcher signature: (http: httpx.AsyncClient, name: str, **kwargs) -> Any
    """
    dispatchers: dict[str, Callable] = {}

    for method_name in dir(manager_cls):
        method = getattr(manager_cls, method_name, None)
        meta: EndpointMeta | None = getattr(method, "__beaver_endpoint__", None)
        if meta is None:
            continue

        async def _dispatch(http, name, _meta=meta, _prefix=mount_prefix, **kwargs):
            path = "/{name}" + _meta.path
            format_kwargs = {"name": name}
            for k in list(kwargs.keys()):
                placeholder = "{" + k + "}"
                if placeholder in path:
                    format_kwargs[k] = kwargs.pop(k)
            url = _prefix + path.format(**format_kwargs)

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
        AsyncBeaverDict, "/dicts"
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


class RemoteList:
    """Remote proxy for AsyncBeaverList.

    Hand-written wrappers around _BUILDERS keep the class IDE-introspectable.
    Local-only methods (dump/load/batched) raise LocalOnlyError.
    """

    _BUILDERS: ClassVar[dict[str, Callable]] = _build_remote_dispatchers(
        AsyncBeaverList, "/lists"
    )

    def __init__(self, http: httpx.AsyncClient, name: str, model=None):
        self._http = http
        self._name = name
        self._model = model

    # --- @expose'd methods ---

    async def count(self) -> int:
        return await self._BUILDERS["count"](self._http, self._name)

    async def get(self, index: int):
        return await self._BUILDERS["get"](self._http, self._name, index=index)

    async def set(self, index: int, value):
        return await self._BUILDERS["set"](
            self._http, self._name, index=index, value=value
        )

    async def delete(self, index: int):
        return await self._BUILDERS["delete"](self._http, self._name, index=index)

    async def contains(self, value) -> bool:
        return await self._BUILDERS["contains"](self._http, self._name, value=value)

    async def push(self, value):
        return await self._BUILDERS["push"](self._http, self._name, value=value)

    async def prepend(self, value):
        return await self._BUILDERS["prepend"](self._http, self._name, value=value)

    async def insert(self, index: int, value):
        return await self._BUILDERS["insert"](
            self._http, self._name, index=index, value=value
        )

    async def pop(self):
        return await self._BUILDERS["pop"](self._http, self._name)

    async def deque(self):
        return await self._BUILDERS["deque"](self._http, self._name)

    async def clear(self):
        return await self._BUILDERS["clear"](self._http, self._name)

    # --- @local_only methods ---

    async def dump(self, *args, **kwargs):
        raise LocalOnlyError(AsyncBeaverList.dump.__beaver_local_only__)

    async def load(self, *args, **kwargs):
        raise LocalOnlyError(AsyncBeaverList.load.__beaver_local_only__)

    def batched(self):
        raise LocalOnlyError(AsyncBeaverList.batched.__beaver_local_only__)


class RemoteQueue:
    """Remote proxy for AsyncBeaverQueue.

    Local-only methods (dump/load) raise LocalOnlyError.
    """

    _BUILDERS: ClassVar[dict[str, Callable]] = _build_remote_dispatchers(
        AsyncBeaverQueue, "/queues"
    )

    def __init__(self, http: httpx.AsyncClient, name: str, model=None):
        self._http = http
        self._name = name
        self._model = model

    # --- @expose'd methods ---

    async def put(self, data, priority: float):
        return await self._BUILDERS["put"](
            self._http, self._name, data=data, priority=priority
        )

    async def peek(self):
        return await self._BUILDERS["peek"](self._http, self._name)

    async def get(self, block: bool = True, timeout: float | None = None):
        return await self._BUILDERS["get"](
            self._http, self._name, block=block, timeout=timeout
        )

    async def count(self) -> int:
        return await self._BUILDERS["count"](self._http, self._name)

    async def clear(self):
        return await self._BUILDERS["clear"](self._http, self._name)

    # --- @local_only methods ---

    async def dump(self, *args, **kwargs):
        raise LocalOnlyError(AsyncBeaverQueue.dump.__beaver_local_only__)

    async def load(self, *args, **kwargs):
        raise LocalOnlyError(AsyncBeaverQueue.load.__beaver_local_only__)


class AsyncBeaverClient:
    """Remote-DB equivalent of AsyncBeaverDB. Use beaver.connect(url) instead of instantiating directly."""

    def __init__(self, base_url: str, api_key: str | None = None):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0)

    def dict(self, name: str, model=None) -> RemoteDict:
        return RemoteDict(self._http, name, model)

    def list(self, name: str, model=None) -> RemoteList:
        return RemoteList(self._http, name, model)

    def queue(self, name: str, model=None) -> RemoteQueue:
        return RemoteQueue(self._http, name, model)

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
        return self._bridged(lambda: self._async.dict(name, model))

    def list(self, name: str, model=None):
        return self._bridged(lambda: self._async.list(name, model))

    def queue(self, name: str, model=None):
        return self._bridged(lambda: self._async.queue(name, model))

    def _bridged(self, factory_sync):
        from .bridge import BeaverBridge

        async def factory():
            return factory_sync()

        future = asyncio.run_coroutine_threadsafe(factory(), self._loop)
        return BeaverBridge(future.result(), self._loop)
