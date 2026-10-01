"""Beaver CLI: data operations, inspection, Studio, serving, and migration."""

from __future__ import annotations

import typer

import beaver
from beaver.dicts import AsyncBeaverDict
from beaver.lists import AsyncBeaverList
from beaver.logs import AsyncBeaverLog
from beaver.queues import AsyncBeaverQueue
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
    if ctx.invoked_subcommand in ("serve", "migrate", "info", "studio"):
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


@app.command()
def migrate(
    source: str = typer.Argument(..., help="Path to the beaver 1.x database."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Destination path (default: <source>.migrated)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be migrated; write nothing."
    ),
):
    """Migrate a beaver 1.x database to the 2.x schema.

    The source is opened read-only and is never modified. The migrated copy is
    written to a new file, so swapping it in stays an explicit, reversible step.
    """
    import asyncio

    from beaver.core import BeaverLegacySchemaError
    from beaver.migrate import format_report, migrate_database, plan_migration

    try:
        if dry_run:
            report = plan_migration(source)
        else:
            destination = output or f"{source}.migrated"
            report = asyncio.run(migrate_database(source, destination))
    except (BeaverLegacySchemaError, FileExistsError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(code=1)

    typer.echo(format_report(report))

    if not report.dry_run:
        typer.echo(
            "\nThe original is untouched. To adopt the migrated copy:\n"
            f"  mv {report.source} {report.source}.1x-backup\n"
            f"  mv {report.destination} {report.source}\n"
            "Keep the backup until you have verified the migration."
        )


@app.command()
def info(
    db: str = typer.Option(..., "--db", help="Path to a local SQLite file."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the inspection report as JSON."
    ),
    include_internal: bool = typer.Option(
        False,
        "--include-internal",
        help="Include Beaver's internal stores in the catalog.",
    ),
):
    """Inspect a Beaver database without modifying it."""
    import asyncio
    import json

    from beaver.core import AsyncBeaverDB
    from beaver.inspection import AsyncBeaverInspector

    async def inspect():
        database = AsyncBeaverDB(db, read_only=True)
        try:
            await database.connect()
            inspector = AsyncBeaverInspector(database)
            return await inspector.info(), await inspector.catalog(
                include_internal=include_internal
            )
        finally:
            await database.close()

    try:
        database_info, stores = asyncio.run(inspect())
    except Exception as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(code=1)

    if json_output:
        payload = {
            "database": database_info.model_dump(mode="json"),
            "stores": [store.model_dump(mode="json") for store in stores],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
        return

    typer.echo("Beaver database")
    typer.echo(f"  Path: {database_info.path}")
    typer.echo(f"  Size: {database_info.size_bytes} bytes")
    typer.echo(f"  Beaver: {database_info.beaver_version}")
    typer.echo(f"  Schema: {database_info.schema_version}")
    typer.echo(f"  Journal: {database_info.journal_mode}")
    typer.echo(f"  Read only: {'yes' if database_info.read_only else 'no'}")
    if database_info.warnings:
        typer.echo("Warnings:")
        for warning in database_info.warnings:
            typer.echo(f"  - {warning}")
    typer.echo("Stores:")
    if not stores:
        typer.echo("  (none)")
    for store in stores:
        count = store.count if store.count is not None else "unknown"
        suffix = "" if store.browsable else " (viewer planned)"
        typer.echo(f"  {store.kind:<8} {store.name} [{count}]{suffix}")


@app.command()
def studio(
    db: str = typer.Option(..., "--db", help="Path to a local SQLite file."),
    port: int = typer.Option(8000, "--port", min=1, max=65535),
):
    """Run the local, read-only Beaver Studio inspector."""
    try:
        import uvicorn

        from beaver.studio import create_studio_app
    except ImportError as exc:
        typer.secho(
            "Studio dependencies are missing; install beaver-db[studio].",
            fg="red",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    host = "127.0.0.1"
    typer.echo(f"Beaver Studio: http://{host}:{port} (read only)")
    uvicorn.run(create_studio_app(db), host=host, port=port)


app.add_typer(
    build_typer_for(
        AsyncBeaverDict,
        manager_accessor=lambda conn, name: conn.dict(name),
        context_key="dict_name",
    ),
    name="dict",
)

app.add_typer(
    build_typer_for(
        AsyncBeaverList,
        manager_accessor=lambda conn, name: conn.list(name),
        context_key="list_name",
    ),
    name="list",
)

app.add_typer(
    build_typer_for(
        AsyncBeaverQueue,
        manager_accessor=lambda conn, name: conn.queue(name),
        context_key="queue_name",
    ),
    name="queue",
)

app.add_typer(
    build_typer_for(
        AsyncBeaverLog,
        manager_accessor=lambda conn, name: conn.log(name),
        context_key="log_name",
    ),
    name="log",
)


if __name__ == "__main__":
    app()
