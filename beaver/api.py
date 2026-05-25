"""@expose decorator + EndpointMeta metadata for SID consumers (CLI, server, client)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointMeta:
    path: str
    method: str
    cli_name: str
    cli_help: str
    body_param: str | None = None


def expose(
    path: str, method: str, cli_name: str, cli_help: str, body_param: str | None = None
):
    """Tag a manager method with SID consumer metadata.

    `path` is relative to the manager prefix (e.g. "/{key}"; the server wraps
    this under "/dicts/{name}"). `body_param` names the kwarg whose value goes
    into the JSON request body for non-GET methods.
    """
    meta = EndpointMeta(
        path=path,
        method=method,
        cli_name=cli_name,
        cli_help=cli_help,
        body_param=body_param,
    )

    def decorator(fn):
        fn.__beaver_endpoint__ = meta
        return fn

    return decorator


def local_only(reason: str):
    """Mark a manager method as local-only — RemoteManager subclasses raise LocalOnlyError."""

    def decorator(fn):
        fn.__beaver_local_only__ = reason
        return fn

    return decorator
