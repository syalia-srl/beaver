"""beaver CLI root: --db / --url / --api-key / --raw, plus `serve` subcommand."""

from __future__ import annotations

import typer

import beaver
from beaver.dicts import AsyncBeaverDict
from .discovery import build_typer_for


app = typer.Typer(no_args_is_help=True)


@app.callback()
def root(
    ctx: typer.Context,
    db: str | None = typer.Option(None, "--db", help="Path to local SQLite file."),
    url: str | None = typer.Option(
        None, "--url", help="URL of a remote beaver server."
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for remote server."
    ),
    raw: bool = typer.Option(
        False, "--raw", help="Strip pretty-print from JSON output."
    ),
):
    if ctx.invoked_subcommand == "serve":
        ctx.obj = {"raw": raw}
        return
    if (db is None) == (url is None):
        raise typer.BadParameter("Pass exactly one of --db or --url")
    conn = beaver.connect(db or url, api_key=api_key)
    ctx.obj = {"conn": conn, "raw": raw}


@app.command()
def serve(
    db: str = typer.Option(..., "--db", help="Path to local SQLite file."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    api_key: str | None = typer.Option(None, "--api-key", envvar="BEAVER_API_KEY"),
):
    """Boot a beaver server backed by a local SQLite file."""
    import asyncio
    import uvicorn
    from beaver.core import AsyncBeaverDB
    from beaver.server import create_app

    async def _init():
        adb = AsyncBeaverDB(db)
        await adb.connect()
        return adb

    adb = asyncio.run(_init())
    fastapi_app = create_app(adb, api_key=api_key)
    uvicorn.run(fastapi_app, host=host, port=port)


app.add_typer(
    build_typer_for(
        AsyncBeaverDict,
        manager_accessor=lambda conn, name: conn.dict(name),
        context_key="dict_name",
    ),
    name="dict",
)


if __name__ == "__main__":
    app()
