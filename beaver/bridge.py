import asyncio
import inspect
from typing import Any, Iterator, AsyncIterator


class _SyncIteratorBridge:
    """
    Helper class that wraps an AsyncIterator (or AsyncGenerator)
    and exposes it as a standard synchronous Iterator.
    """

    def __init__(self, async_iter: AsyncIterator, loop: asyncio.AbstractEventLoop):
        self._async_iter = async_iter
        self._loop = loop

    def __iter__(self):
        return self

    def __next__(self):
        # Define a coroutine to fetch the next item safely on the background loop
        async def step():
            try:
                # Use the builtin anext() (Python 3.10+)
                return await anext(self._async_iter)
            except StopAsyncIteration:
                # Raise a special sentinel to signal the loop to stop
                return StopAsyncIteration

        # Run the step on the reactor thread
        future = asyncio.run_coroutine_threadsafe(step(), self._loop)
        result = future.result()

        # Propagate the stop signal as a synchronous StopIteration
        if result is StopAsyncIteration:
            raise StopIteration

        return result


class BeaverBridge:
    """
    A generic synchronous bridge that proxies access to an asynchronous object
    running on a background asyncio loop.

    This class enables the "Portal Pattern", allowing standard synchronous
    Python code to interact with the Async-First core of BeaverDB safely.
    """

    def __init__(self, async_obj: Any, loop: asyncio.AbstractEventLoop):
        self._async_obj = async_obj
        self._loop = loop

    def _run(self, coro: Any) -> Any:
        """
        Helper to run a coroutine on the background loop and block
        the calling thread until the result is ready.
        """
        if not inspect.iscoroutine(coro):
            return coro

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def __getattr__(self, name: str) -> Any:
        """
        Dynamically intercepts method calls and properties.
        """
        try:
            attr = getattr(self._async_obj, name)
        except AttributeError:
            raise AttributeError(
                f"'{type(self._async_obj).__name__}' object has no attribute '{name}'"
            )

        # If it is a method, wrap it to handle Coroutines AND AsyncGenerators
        if inspect.ismethod(attr) or inspect.isfunction(attr):

            def wrapper(*args, **kwargs):
                # 1. Call the method (this is fast/non-blocking for async defs)
                result = attr(*args, **kwargs)

                # 2. Check if it returned an Async Generator (e.g. .keys(), .live())
                if inspect.isasyncgen(result):
                    return _SyncIteratorBridge(result, self._loop)

                # 3. Otherwise, run it (handles coroutines or regular values)
                return self._run(result)

            return wrapper

        return attr

    def __repr__(self) -> str:
        async def safe_repr():
            return repr(self._async_obj)

        try:
            return self._run(safe_repr())
        except Exception:
            return f"<BeaverBridge wrapping {type(self._async_obj).__name__}>"

    # --- Context Manager ---

    def __enter__(self):
        if not hasattr(self._async_obj, "__aenter__"):
            raise TypeError(
                f"Object of type {type(self._async_obj).__name__} does not support context manager protocol"
            )

        raw_result = self._run(self._async_obj.__aenter__())

        if raw_result is self._async_obj:
            return self

        return BeaverBridge(raw_result, self._loop)

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._run(self._async_obj.__aexit__(exc_type, exc_val, exc_tb))

    # --- Magic Methods (Container Emulation) ---

    def __len__(self) -> int:
        if hasattr(self._async_obj, "count"):
            return self._run(self._async_obj.count())
        raise TypeError(f"Object of type {type(self._async_obj).__name__} has no len()")

    def __getitem__(self, key: Any) -> Any:
        if hasattr(self._async_obj, "get"):
            return self._run(self._async_obj.get(key))
        raise TypeError(
            f"Object of type {type(self._async_obj).__name__} is not subscriptable"
        )

    def __setitem__(self, key: Any, value: Any):
        if hasattr(self._async_obj, "set"):
            return self._run(self._async_obj.set(key, value))
        raise TypeError(
            f"Object of type {type(self._async_obj).__name__} does not support item assignment"
        )

    def __delitem__(self, key: Any):
        if hasattr(self._async_obj, "delete"):
            return self._run(self._async_obj.delete(key))
        raise TypeError(
            f"Object of type {type(self._async_obj).__name__} does not support item deletion"
        )

    def __contains__(self, key: Any) -> bool:
        if hasattr(self._async_obj, "contains"):
            return self._run(self._async_obj.contains(key))
        return False

    def __iter__(self) -> Iterator[Any]:
        """
        Bridges AsyncIterator -> SyncIterator using the helper class.
        """
        if not hasattr(self._async_obj, "__aiter__"):
            raise TypeError(
                f"Object of type {type(self._async_obj).__name__} is not iterable"
            )

        # Create the async iterator on the background thread
        async def get_iter():
            return self._async_obj.__aiter__()

        async_iter = self._run(get_iter())
        return _SyncIteratorBridge(async_iter, self._loop)
