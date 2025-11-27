import asyncio
import inspect
from typing import Any, Iterator, Callable

class BeaverBridge:
    """
    A generic synchronous bridge that proxies access to an asynchronous object
    running on a background asyncio loop.

    This class enables the "Portal Pattern", allowing standard synchronous
    Python code to interact with the Async-First core of BeaverDB safely.

    It handles:
    1. Dynamic method proxying (calling .get() -> schedules await async_obj.get())
    2. Context manager mapping (__enter__ -> await __aenter__)
    3. Magic method mapping (__getitem__ -> await get_item)
    """

    def __init__(self, async_obj: Any, loop: asyncio.AbstractEventLoop):
        self._async_obj = async_obj
        self._loop = loop

    def _run(self, coro: Any) -> Any:
        """
        Helper to run a coroutine (or return a value) on the background loop
        and block the calling thread until the result is ready.
        """
        # If it's not a coroutine (e.g., a simple property value), return as-is
        if not inspect.iscoroutine(coro):
            return coro

        # Schedule the coroutine on the reactor thread
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        # Block this thread until the result returns
        return future.result()

    def __getattr__(self, name: str) -> Any:
        """
        Dynamically intercepts method calls and properties.
        """
        # 1. Get the attribute from the underlying async object
        try:
            attr = getattr(self._async_obj, name)
        except AttributeError:
            raise AttributeError(
                f"'{type(self._async_obj).__name__}' object has no attribute '{name}'"
            )

        # 2. If it is a method/function, we assume it *might* return a coroutine.
        # We wrap it to ensure the result (coroutine) is passed to self._run().
        # Note: Calling an `async def` function from the main thread is safe;
        # it just returns a coroutine object without executing body code.
        if inspect.ismethod(attr) or inspect.isfunction(attr):
            def wrapper(*args, **kwargs):
                result = attr(*args, **kwargs)
                return self._run(result)
            return wrapper

        # 3. If it's a property/attribute, return it directly.
        # (Assuming properties are read-only or thread-safe immutable values)
        return attr

    def __repr__(self) -> str:
        # Run the repr on the loop to be thread-safe regarding internal state
        async def safe_repr():
            return repr(self._async_obj)

        try:
            return self._run(safe_repr())
        except Exception:
            return f"<BeaverBridge wrapping {type(self._async_obj).__name__}>"

    # --- Context Manager ---

    def __enter__(self):
        """
        Maps synchronous 'with' to asynchronous 'async with'.
        Wraps the result in a new Bridge if it's a different object.
        """
        # 1. Run the async __aenter__ and get the raw result
        if not hasattr(self._async_obj, "__aenter__"):
             raise TypeError(f"Object of type {type(self._async_obj).__name__} does not support context manager protocol")

        raw_result = self._run(self._async_obj.__aenter__())

        # 2. If the result is the object itself (common pattern), return self (the bridge)
        if raw_result is self._async_obj:
            return self

        # 3. Otherwise (e.g. .batched() returning a Batch object), wrap it in a new Bridge
        return BeaverBridge(raw_result, self._loop)

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._run(self._async_obj.__aexit__(exc_type, exc_val, exc_tb))

    # --- Magic Methods (Container Emulation) ---
    # Python does not look up magic methods via __getattr__, so they must
    # be explicitly defined. We map them to explicit async methods on the core.

    def __len__(self) -> int:
        # Maps len(obj) -> await obj.count()
        if hasattr(self._async_obj, "count"):
             return self._run(self._async_obj.count())
        raise TypeError(f"Object of type {type(self._async_obj).__name__} has no len()")

    def __getitem__(self, key: Any) -> Any:
        # Maps obj[key] -> await obj.get_item(key)
        if hasattr(self._async_obj, "get"):
            return self._run(self._async_obj.get(key))
        raise TypeError(f"Object of type {type(self._async_obj).__name__} is not subscriptable")

    def __setitem__(self, key: Any, value: Any):
        # Maps obj[key] = value -> await obj.set_item(key, value)
        if hasattr(self._async_obj, "set"):
            return self._run(self._async_obj.set(key, value))
        raise TypeError(f"Object of type {type(self._async_obj).__name__} does not support item assignment")

    def __delitem__(self, key: Any):
        # Maps del obj[key] -> await obj.del_item(key)
        if hasattr(self._async_obj, "delete"):
            return self._run(self._async_obj.delete(key))
        raise TypeError(f"Object of type {type(self._async_obj).__name__} does not support item deletion")

    def __contains__(self, key: Any) -> bool:
        # Maps key in obj -> await obj.contains(key)
        if hasattr(self._async_obj, "contains"):
            return self._run(self._async_obj.contains(key))
        # Fallback: We can't easily fallback to iteration in async land efficiently
        return False

    def __iter__(self) -> Iterator[Any]:
        """
        Bridges AsyncIterator -> SyncIterator.
        Fetches items one-by-one from the async iterator on the background thread.
        """
        if not hasattr(self._async_obj, "__aiter__"):
             raise TypeError(f"Object of type {type(self._async_obj).__name__} is not iterable")

        async_iter = self._async_obj.__aiter__()

        while True:
            try:
                # Use anext() to get the next coroutine from the async iterator
                coro = anext(async_iter)
                yield self._run(coro)
            except StopAsyncIteration:
                break