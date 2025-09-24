import json
from typing import Protocol, Type, runtime_checkable, Self


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


class Model:
    """A lightweight base model that automatically provides JSON serialization."""
    def __init__(self, **kwargs) -> None:
        for k,v in kwargs.items():
            setattr(self, k, v)

    def model_dump_json(self) -> str:
        """Serializes the dataclass instance to a JSON string."""
        return json.dumps(self.__dict__)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes) -> Self:
        """Deserializes a JSON string into a new instance of the dataclass."""
        return cls(**json.loads(json_data))

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={repr(v)}" for k,v in self.__dict__.items())
        return f"{self.__class__.__name__}({attrs})"
