from dataclasses import dataclass
from typing import Any, cast, overload


@dataclass
class Filter:
    path: str
    operator: str
    value: Any


class Query[T]:
    def __init__(self, model: type[T] | None = None, path: str = "") -> None:
        self._model = model
        self._path = path

    def __getattr__(self, name: str):
        new_path = f"{self._path}.{name}" if self._path else name
        return Query(self._model, new_path)

    # --- Standard Operators ---

    def __eq__(self, other) -> Filter:  # type: ignore
        return Filter(self._path, "==", other)

    def __ne__(self, other) -> Filter:  # type: ignore
        return Filter(self._path, "!=", other)

    # --- Arithmetic Operators

    def __gt__(self, other) -> Filter:
        return Filter(self._path, ">", other)

    def __ge__(self, other) -> Filter:
        return Filter(self._path, ">=", other)

    def __lt__(self, other) -> Filter:
        return Filter(self._path, "<", other)

    def __le__(self, other) -> Filter:
        return Filter(self._path, "<=", other)


@overload
def q[T](model_or_path: type[T]) -> T:
    pass

@overload
def q(model_or_path: str) -> Query:
    pass

@overload
def q() -> Query:
    pass

def q(model_or_path: type | str | None = None) -> Any:
    if isinstance(model_or_path, type):
        return Query(model=model_or_path)

    if isinstance(model_or_path, str):
        return Query(path=model_or_path)

    return Query()
