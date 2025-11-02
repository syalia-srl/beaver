import typer
import rich
from typing_extensions import Annotated

import beaver
from beaver import BeaverDB

# Import the command group from the new file
from beaver.cli import dicts as dicts_cli

# --- Main App ---
app = typer.Typer()

# Register the command group
app.add_typer(dicts_cli.app)


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


if __name__ == "__main__":
    app()