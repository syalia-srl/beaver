import typer
import rich
import rich.table
from typing_extensions import Annotated

import beaver
from beaver import BeaverDB

# Import the command group from the new file
from beaver.cli import dicts as dicts_cli
from beaver.cli import lists as lists_cli
from beaver.cli import queues as queues_cli
from beaver.cli import blobs as blobs_cli
from beaver.cli import locks as locks_cli
from beaver.cli import logs as logs_cli
from beaver.cli import channels as channels_cli
from beaver.cli import collections as collections_cli

# --- Main App ---
app = typer.Typer()

# Register the command group
app.add_typer(dicts_cli.app)
app.add_typer(lists_cli.app)
app.add_typer(queues_cli.app)
app.add_typer(blobs_cli.app)
app.add_typer(locks_cli.app)
app.add_typer(logs_cli.app)
app.add_typer(channels_cli.app)
app.add_typer(collections_cli.app)


def version_callback(value: bool):
    if value:
        print(beaver.__version__)
        raise typer.Exit()

@app.callback()
def main(
    ctx: typer.Context,
    database: Annotated[
        str, typer.Option(help="The path to the BeaverDB database file.")
    ] = "beaver.db",
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
):
    """
    BeaverDB command-line interface.
    """
    try:
        # Store the db instance in the context for all subcommands
        ctx.obj = {"db": BeaverDB(database)}
    except Exception as e:
        rich.print(f"[bold red]Error opening database:[/] {e}")
        raise typer.Exit(code=1)

# --- Serve Command ---
@app.command()
def serve(
    database: Annotated[
        str, typer.Option(help="The path to the BeaverDB database file.")
    ] = "beaver.db",
    host: Annotated[str, typer.Option(help="The host to bind the server to.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="The port to run the server on.")] = 8000,
):
    """Starts a REST API server for the BeaverDB database."""
    try:
        from beaver import server
    except ImportError:
        rich.print(
            "[red]Error:[/] To use the serve command, please install the server dependencies:\n"
            'pip install "beaver-db[server]"'
        )
        raise typer.Exit(code=1)
    server.serve(database, host=host, port=port)


@app.command()
def info(ctx: typer.Context):
    """
    Displays a summary of all data structures in the database.
    """
    db: BeaverDB = ctx.obj["db"]
    rich.print(f"[bold]Database Summary: {db._db_path}[/bold]")

    table = rich.table.Table(title="BeaverDB Contents")
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Count", style="magenta", justify="right")

    try:
        # Dictionaries
        for name in db.dicts:
            table.add_row("Dict", name, str(len(db.dict(name))))
        # Lists
        for name in db.lists:
            table.add_row("List", name, str(len(db.list(name))))
        # Queues
        for name in db.queues:
            table.add_row("Queue", name, str(len(db.queue(name))))
        # Collections
        for name in db.collections:
            table.add_row("Collection", name, str(len(db.collection(name))))
        # Blob Stores
        for name in db.blobs:
            table.add_row("Blob Store", name, str(len(db.blob(name))))
        # Logs
        for name in db.logs:
            table.add_row("Log", name, "N/A (len not supported)")
        # Active Locks
        for name in db.locks:
             table.add_row("Active Lock", name, "1")

        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()