import base64
import json
import time
from typing import (
    IO,
    Any,
    Iterator,
    Tuple,
    overload,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .security import Cipher

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


@runtime_checkable
class IBeaverDict[T](Protocol):
    """
    The Synchronous Protocol exposed to the user via BeaverBridge.
    """

    def __getitem__(self, key: str) -> T: ...
    def __setitem__(self, key: str, value: T) -> None: ...
    def __delitem__(self, key: str) -> None: ...
    def __len__(self) -> int: ...
    def __contains__(self, key: str) -> bool: ...
    def __iter__(self) -> Iterator[str]: ...

    def get(self, key: str) -> T: ...
    def set(self, key: str, value: T, ttl_seconds: float | None = None) -> None: ...
    def delete(self, key: str) -> None: ...

    def fetch(self, key: str, default: Any = None) -> T | Any: ...
    def pop(self, key: str, default: Any = None) -> T | Any: ...
    def keys(self) -> Iterator[str]: ...
    def values(self) -> Iterator[T]: ...
    def items(self) -> Iterator[Tuple[str, T]]: ...
    def clear(self) -> None: ...
    def count(self) -> int: ...
    def dump(self, fp: IO[str] | None = None) -> dict | None: ...


class AsyncBeaverDict[T: BaseModel](AsyncBeaverBase[T]):
    """
    A wrapper providing a Pythonic interface to a dictionary in the database.
    Refactored for Async-First architecture (v2.0).
    """

    def __init__(
        self,
        name: str,
        db: "AsyncBeaverDB",
        model: type[T] | None = None,
        secret: str | None = None,
    ):
        super().__init__(name, db, model)
        self._cipher: Cipher | None = None
        self._secret_arg = secret

    async def _init(self):
        """Async initialization hook."""
        if self._secret_arg or not self.is_system():
            await self._setup_security(self._secret_arg)

    def is_system(self):
        return self._name in [
            "__metadata__",
            "__security__",
            "__beaver_event_registry__",
        ]

    async def _setup_security(self, secret: str | None):
        """
        Initializes the encryption cipher.
        Reads directly from the internal __beaver_dicts__ table to avoid recursion.
        """
        if self._name == "__security__":
            if secret:
                raise ValueError(
                    "The internal '__security__' dictionary cannot be encrypted."
                )
            return

        cursor = await self.connection.execute(
            "SELECT value FROM __beaver_dicts__ WHERE dict_name = ? AND key = ?",
            ("__security__", self._name),
        )
        row = await cursor.fetchone()
        metadata = json.loads(row["value"]) if row else None

        if secret is None:
            if metadata:
                raise ValueError(
                    f"Dictionary '{self._name}' is encrypted. You must provide a secret to open it."
                )
            return

        if metadata:
            try:
                salt = base64.b64decode(metadata["salt"])
                verifier_encrypted = base64.b64decode(metadata["verifier"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    f"Corrupted security metadata for dictionary '{self._name}'."
                )

            cipher = Cipher(secret, salt=salt)

            try:
                decrypted = cipher.decrypt(verifier_encrypted)
                if decrypted != b"beaver-secure":
                    raise ValueError("Invalid secret.")
            except Exception:
                raise ValueError(f"Invalid secret for dictionary '{self._name}'.")

            self._cipher = cipher
        else:
            cipher = Cipher(secret)
            salt = cipher.salt
            verifier_encrypted = cipher.encrypt(b"beaver-secure")

            new_metadata = {
                "salt": base64.b64encode(salt).decode("utf-8"),
                "verifier": base64.b64encode(verifier_encrypted).decode("utf-8"),
                "created_at": time.time(),
            }

            await self.connection.execute(
                "INSERT OR REPLACE INTO __beaver_dicts__ (dict_name, key, value, expires_at) VALUES (?, ?, ?, ?)",
                ("__security__", self._name, json.dumps(new_metadata), None),
            )
            await self.connection.commit()
            self._cipher = cipher

    def _serialize(self, value: T) -> str:
        json_str = super()._serialize(value)
        if self._cipher:
            encrypted_bytes = self._cipher.encrypt(json_str.encode("utf-8"))
            return base64.urlsafe_b64encode(encrypted_bytes).decode("utf-8")
        return json_str

    def _deserialize(self, value: str) -> T:
        json_str = value
        if self._cipher:
            try:
                encrypted_bytes = base64.urlsafe_b64decode(value)
                json_str = self._cipher.decrypt(encrypted_bytes).decode("utf-8")
            except Exception as e:
                raise ValueError(
                    f"Failed to decrypt value in dictionary '{self._name}'."
                ) from e
        return super()._deserialize(json_str)

    # --- Core Async API ---

    @emits("set", payload=lambda key, *args, **kwargs: dict(key=key))
    @atomic
    async def set(self, key: str, value: T, ttl_seconds: float | None = None):
        """Sets a value for a key."""
        if self._secret_arg and not self._cipher:
            await self._setup_security(self._secret_arg)

        expires_at = None
        if ttl_seconds is not None:
            if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
                raise ValueError("ttl_seconds must be a positive number.")
            expires_at = time.time() + ttl_seconds

        serialized_value = self._serialize(value)

        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_dicts__
            (dict_name, key, value, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (self._name, key, serialized_value, expires_at),
        )

    @atomic
    async def get(self, key: str) -> T:
        """Retrieves a value for a key. Raises KeyError if missing or expired."""
        if self._secret_arg and not self._cipher:
            await self._setup_security(self._secret_arg)

        cursor = await self.connection.execute(
            "SELECT value, expires_at FROM __beaver_dicts__ WHERE dict_name = ? AND key = ?",
            (self._name, key),
        )
        result = await cursor.fetchone()

        if result is None:
            raise KeyError(f"Key '{key}' not found in dictionary '{self._name}'")

        raw_value, expires_at = result["value"], result["expires_at"]

        if expires_at is not None and time.time() > expires_at:
            await self.connection.execute(
                "DELETE FROM __beaver_dicts__ WHERE dict_name = ? AND key = ?",
                (self._name, key),
            )
            raise KeyError(
                f"Key '{key}' not found in dictionary '{self._name}' (expired)"
            )

        return self._deserialize(raw_value)

    @emits("del", payload=lambda key, *args, **kwargs: dict(key=key))
    @atomic
    async def delete(self, key: str):
        """Deletes a key. Raises KeyError if missing."""
        cursor = await self.connection.execute(
            "DELETE FROM __beaver_dicts__ WHERE dict_name = ? AND key = ?",
            (self._name, key),
        )

        if cursor.rowcount == 0:
            raise KeyError(f"Key '{key}' not found in dictionary '{self._name}'")

    async def fetch(self, key: str, default: Any = None) -> T | Any:
        try:
            return await self.get(key)
        except KeyError:
            return default

    @atomic
    async def pop(self, key: str, default: Any = None) -> T | Any:
        try:
            value = await self.get(key)
            await self.delete(key)
            return value
        except KeyError:
            return default

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_dicts__ WHERE dict_name = ?", (self._name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def contains(self, key: str) -> bool:
        cursor = await self.connection.execute(
            "SELECT 1 FROM __beaver_dicts__ WHERE dict_name = ? AND key = ? LIMIT 1",
            (self._name, key),
        )
        return await cursor.fetchone() is not None

    @emits("clear", payload=lambda *args, **kwargs: dict())
    @atomic
    async def clear(self):
        await self.connection.execute(
            "DELETE FROM __beaver_dicts__ WHERE dict_name = ?",
            (self._name,),
        )

    # --- Iterators (Async Generators) ---

    async def __aiter__(self):
        async for key in self.keys():
            yield key

    async def keys(self):
        cursor = await self.connection.execute(
            "SELECT key FROM __beaver_dicts__ WHERE dict_name = ?", (self._name,)
        )
        async for row in cursor:
            yield row["key"]

    async def values(self):
        cursor = await self.connection.execute(
            "SELECT value FROM __beaver_dicts__ WHERE dict_name = ?", (self._name,)
        )
        async for row in cursor:
            yield self._deserialize(row["value"])

    async def items(self):
        cursor = await self.connection.execute(
            "SELECT key, value FROM __beaver_dicts__ WHERE dict_name = ?", (self._name,)
        )
        async for row in cursor:
            yield (row["key"], self._deserialize(row["value"]))

    async def dump(self, fp: IO[str] | None = None) -> dict | None:
        items = []
        async for k, v in self.items():
            val = v
            if self._model and isinstance(v, BaseModel):
                val = json.loads(v.model_dump_json())
            items.append({"key": k, "value": val})

        dump_obj = {
            "metadata": {
                "type": "Dict",
                "name": self._name,
                "count": len(items),
                "encrypted": self._cipher is not None,
            },
            "items": items,
        }

        if fp:
            json.dump(dump_obj, fp, indent=2)
            return None

        return dump_obj
