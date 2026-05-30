"""Build a typer app for a manager class by introspecting @expose'd methods."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Callable

import typer

from ..api import EndpointMeta


def _read_json_value(raw: str | None) -> object:
    """Decode a CLI-supplied JSON value. '-' reads from stdin."""
    if raw is None:
        return None
    if raw == "-":
        raw = sys.stdin.read()
    return json.loads(raw)


def _build_command(method_name: str, meta: EndpointMeta, manager_accessor: Callable):
    """Return a typer-friendly function that invokes the manager method and prints JSON.

    Each command relies on ctx.obj carrying both the connection and the manager
    instance name, so commands accept only the per-method args.
    """
    # --- dict shapes ---
    if method_name == "set" and meta.path == "/{key}":

        def cmd(
            ctx: typer.Context,
            key: str,
            value: str = typer.Argument(None),
            ttl_seconds: float | None = typer.Option(None, "--ttl"),
        ):
            decoded = _read_json_value(value)
            _run(
                ctx,
                manager_accessor,
                method_name,
                key=key,
                value=decoded,
                ttl_seconds=ttl_seconds,
            )

    elif method_name == "pop" and meta.path == "/{key}/pop":

        def cmd(
            ctx: typer.Context,
            key: str,
            default: str = typer.Option(None, "--default"),
        ):
            decoded = _read_json_value(default)
            _run(ctx, manager_accessor, method_name, key=key, default=decoded)

    elif method_name == "fetch":

        def cmd(
            ctx: typer.Context,
            key: str,
            default: str = typer.Option(None, "--default"),
        ):
            decoded = _read_json_value(default)
            _run(ctx, manager_accessor, method_name, key=key, default=decoded)

    elif method_name in ("get", "delete", "contains") and "{key}" in meta.path:

        def cmd(ctx: typer.Context, key: str):
            _run(ctx, manager_accessor, method_name, key=key)

    # --- list shapes (path carries {index}) ---
    elif method_name == "get" and "{index}" in meta.path:

        def cmd(ctx: typer.Context, index: int):
            _run(ctx, manager_accessor, method_name, index=index)

    elif method_name == "delete" and "{index}" in meta.path:

        def cmd(ctx: typer.Context, index: int):
            _run(ctx, manager_accessor, method_name, index=index)

    elif method_name == "set" and "{index}" in meta.path:

        def cmd(ctx: typer.Context, index: int, value: str = typer.Argument(None)):
            decoded = _read_json_value(value)
            _run(ctx, manager_accessor, method_name, index=index, value=decoded)

    elif method_name == "contains" and meta.path == "/contains":

        def cmd(ctx: typer.Context, value: str = typer.Argument(None)):
            decoded = _read_json_value(value)
            _run(ctx, manager_accessor, method_name, value=decoded)

    elif method_name in ("push", "prepend"):

        def cmd(ctx: typer.Context, value: str = typer.Argument(None)):
            decoded = _read_json_value(value)
            _run(ctx, manager_accessor, method_name, value=decoded)

    elif method_name == "insert":

        def cmd(ctx: typer.Context, index: int, value: str = typer.Argument(None)):
            decoded = _read_json_value(value)
            _run(ctx, manager_accessor, method_name, index=index, value=decoded)

    elif method_name in ("pop", "deque") and "{key}" not in meta.path:

        def cmd(ctx: typer.Context):
            _run(ctx, manager_accessor, method_name)

    # --- queue shapes ---
    elif method_name == "put":

        def cmd(
            ctx: typer.Context,
            data: str = typer.Argument(None),
            priority: float = typer.Option(..., "--priority"),
        ):
            decoded = _read_json_value(data)
            _run(ctx, manager_accessor, method_name, data=decoded, priority=priority)

    elif method_name == "peek":

        def cmd(ctx: typer.Context):
            _run(ctx, manager_accessor, method_name)

    elif method_name == "get" and meta.path == "/get":  # queue.get

        def cmd(
            ctx: typer.Context,
            block: bool = typer.Option(True, "--block/--no-block"),
            timeout: float | None = typer.Option(None, "--timeout"),
        ):
            _run(ctx, manager_accessor, method_name, block=block, timeout=timeout)

    # --- shared no-arg shapes ---
    elif method_name in ("count", "clear"):

        def cmd(ctx: typer.Context):
            _run(ctx, manager_accessor, method_name)

    else:
        raise NotImplementedError(f"No CLI shape for {method_name} (path={meta.path})")

    cmd.__name__ = meta.cli_name
    cmd.__doc__ = meta.cli_help
    return cmd


def _run(ctx: typer.Context, manager_accessor: Callable, method_name: str, **kwargs):
    conn = ctx.obj["conn"]
    name = ctx.obj["instance_name"]
    raw = ctx.obj.get("raw", False)
    mgr = manager_accessor(conn, name)
    _invoke_and_print(mgr, method_name, raw, **kwargs)


def _invoke_and_print(manager, method_name: str, raw: bool, **kwargs):
    """Call `manager.method_name(**kwargs)`. Manager may be sync (BeaverBridge) or async."""
    method = getattr(manager, method_name)
    result = method(**kwargs)
    if asyncio.iscoroutine(result):
        result = asyncio.new_event_loop().run_until_complete(result)
    if result is None:
        return
    # NamedTuples (e.g. QueueItem) JSON-dump as arrays; surface them as dicts.
    if isinstance(result, tuple) and hasattr(result, "_asdict"):
        result = result._asdict()
    if raw:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=2))


def build_typer_for(
    manager_cls, manager_accessor: Callable, context_key: str
) -> typer.Typer:
    """Walk @expose'd methods on manager_cls; register one typer command per method.

    The returned Typer group's callback takes a positional `name` argument (the
    manager instance name, e.g. dict/list/queue name) and stashes it in
    ctx.obj["instance_name"]. Commands read it from ctx.obj.
    """
    app = typer.Typer(no_args_is_help=True)

    @app.callback()
    def _group(ctx: typer.Context, name: str):
        if ctx.obj is None:
            ctx.obj = {}
        ctx.obj["instance_name"] = name
        ctx.obj[context_key] = name

    for method_name in dir(manager_cls):
        method = getattr(manager_cls, method_name, None)
        meta: EndpointMeta | None = getattr(method, "__beaver_endpoint__", None)
        if meta is None:
            continue
        cmd = _build_command(method_name, meta, manager_accessor)
        app.command(name=meta.cli_name, help=meta.cli_help)(cmd)
    return app
