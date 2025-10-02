import typer
import rich
from typing_extensions import Annotated

app = typer.Typer()


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
        from . import server
    except ImportError:
        rich.print(
            "[red]Error:[/] To use the serve command, please install the server dependencies:\n"
            'pip install "beaver-db[server]"'
        )
        raise typer.Exit(code=1)

    server.serve(database, host=host, port=port)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def client(
    ctx: typer.Context,
    database: Annotated[
        str, typer.Option(help="The path to the BeaverDB database file.")
    ] = "beaver.db",
):
    """
    Provides a command-line client to interact with the database.

    All arguments after 'client' are passed directly to the database object.
    Example: beaver client --database my.db dict my_dict get my_key
    """
    try:
        import fire
        from .core import BeaverDB
    except ImportError:
        rich.print(
            "[red]Error:[/] To use the client command, please install the CLI dependencies:\n"
            'pip install "beaver-db[cli]"'
        )
        raise typer.Exit(code=1)

    db = BeaverDB(database)
    # The arguments for fire are passed via ctx.args, which captures everything
    # after the 'client' command.
    fire.Fire(db, command=ctx.args)


if __name__ == "__main__":
    app()
