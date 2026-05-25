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

    Each command relies on ctx.obj carrying both the connection and the dict name,
    so commands accept only the per-method args (key, value, etc).
    """
    if method_name == "set":

        def cmd(
            ctx: typer.Context,
            key: str,
            value: str = typer.Argument(None),
            ttl_seconds: float | None = typer.Option(None, "--ttl"),
        ):
            conn = ctx.obj["conn"]
            name = ctx.obj["dict_name"]
            raw = ctx.obj.get("raw", False)
            decoded = _read_json_value(value)
            mgr = manager_accessor(conn, name)
            _invoke_and_print(
                mgr, method_name, raw, key=key, value=decoded, ttl_seconds=ttl_seconds
            )

    elif method_name == "pop":

        def cmd(
            ctx: typer.Context,
            key: str,
            default: str = typer.Option(None, "--default"),
        ):
            conn = ctx.obj["conn"]
            name = ctx.obj["dict_name"]
            raw = ctx.obj.get("raw", False)
            decoded = _read_json_value(default)
            mgr = manager_accessor(conn, name)
            _invoke_and_print(mgr, method_name, raw, key=key, default=decoded)

    elif method_name == "fetch":

        def cmd(
            ctx: typer.Context,
            key: str,
            default: str = typer.Option(None, "--default"),
        ):
            conn = ctx.obj["conn"]
            name = ctx.obj["dict_name"]
            raw = ctx.obj.get("raw", False)
            decoded = _read_json_value(default)
            mgr = manager_accessor(conn, name)
            _invoke_and_print(mgr, method_name, raw, key=key, default=decoded)

    elif method_name in ("get", "delete", "contains"):

        def cmd(ctx: typer.Context, key: str):
            conn = ctx.obj["conn"]
            name = ctx.obj["dict_name"]
            raw = ctx.obj.get("raw", False)
            mgr = manager_accessor(conn, name)
            _invoke_and_print(mgr, method_name, raw, key=key)

    elif method_name in ("count", "clear"):

        def cmd(ctx: typer.Context):
            conn = ctx.obj["conn"]
            name = ctx.obj["dict_name"]
            raw = ctx.obj.get("raw", False)
            mgr = manager_accessor(conn, name)
            _invoke_and_print(mgr, method_name, raw)

    else:
        raise NotImplementedError(f"No CLI shape for {method_name} in slice 1")

    cmd.__name__ = meta.cli_name
    cmd.__doc__ = meta.cli_help
    return cmd


def _invoke_and_print(manager, method_name: str, raw: bool, **kwargs):
    """Call `manager.method_name(**kwargs)`. Manager may be sync (BeaverBridge) or async."""
    method = getattr(manager, method_name)
    result = method(**kwargs)
    if asyncio.iscoroutine(result):
        result = asyncio.new_event_loop().run_until_complete(result)
    if result is None:
        return
    if raw:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=2))


def build_typer_for(
    manager_cls, manager_accessor: Callable, context_key: str
) -> typer.Typer:
    """Walk @expose'd methods on manager_cls; register one typer command per method.

    The returned Typer group's callback takes a positional `name` argument (the
    manager instance name, e.g. dict name) and stashes it in ctx.obj under
    `context_key`. Commands read it from ctx.obj.
    """
    app = typer.Typer(no_args_is_help=True)

    @app.callback()
    def _group(ctx: typer.Context, name: str):
        if ctx.obj is None:
            ctx.obj = {}
        ctx.obj[context_key] = name

    for method_name in dir(manager_cls):
        method = getattr(manager_cls, method_name, None)
        meta: EndpointMeta | None = getattr(method, "__beaver_endpoint__", None)
        if meta is None:
            continue
        cmd = _build_command(method_name, meta, manager_accessor)
        app.command(name=meta.cli_name, help=meta.cli_help)(cmd)
    return app
