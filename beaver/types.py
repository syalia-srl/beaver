import json
import sqlite3
from typing import Protocol, Type, runtime_checkable, Self

from beaver.cache import ICache


@runtime_checkable
class JsonSerializable[T](Protocol):
    """
    A protocol for objects that can be serialized to and from JSON,
    compatible with Pydantic's `BaseModel`.
    """

    def model_dump_json(self) -> str:
        """Serializes the model to a JSON string."""
        ...

    @classmethod
    def model_validate_json(cls: Type[T], json_data: str | bytes) -> T:
        """Deserializes a JSON string into a model instance."""
        ...


class _ModelEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that recursively serializes Model instances.
    """
    def default(self, o):
        if isinstance(o, Model):
            # If the object is a Model instance, return its __dict__.
            # The JSONEncoder will then recursively serialize this dict.
            return o.__dict__
        # Let the base class handle built-in types
        return super().default(o)


class Model:
    """A lightweight base model that automatically provides JSON serialization."""
    def __init__(self, **kwargs) -> None:
        for k,v in kwargs.items():
            setattr(self, k, v)

    def model_dump_json(self) -> str:
        """Serializes the dataclass instance to a JSON string."""
        # Use the custom _ModelEncoder to handle self and any nested Models
        return json.dumps(self, cls=_ModelEncoder)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes) -> Self:
        """Deserializes a JSON string into a new instance of the dataclass."""
        # Note: This deserializes nested objects as dicts, not Model instances.
        return cls(**json.loads(json_data))

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={repr(v)}" for k,v in self.__dict__.items())
        return f"{self.__class__.__name__}({attrs})"


def stub(msg: str):
    class Stub:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattribute__(self, name: str):
            raise TypeError(msg)

        def __call__(self, *args, **kwds):
            raise TypeError(msg)

    return Stub


class IDatabase(Protocol):
    @property
    def connection(self) -> sqlite3.Connection: ...
    def cache(self, key:str) -> ICache: ...
