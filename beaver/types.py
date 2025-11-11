import json
import sqlite3
from typing import Any, Callable, Optional, Protocol, Type, Self, runtime_checkable

from .cache import ICache


class IDatabase(Protocol):
    @property
    def connection(self) -> sqlite3.Connection: ...
    def cache(self, key: str) -> "ICache": ...
    def singleton[T, M](
        self, cls: Type[M], name: str, model: Type[T] | None = None, **kwargs
    ) -> M: ...
    def emit(self, topic: str, event: str, payload: dict) -> bool: ...
    def on(
        self,
        topic: str,
        event: str,
        callback: Callable,
    ): ...
    def off(
        self,
        topic: str,
        event: str,
        callback: Callable,
    ): ...


@runtime_checkable
class IResourceManager(Protocol):
    def close(self): ...
