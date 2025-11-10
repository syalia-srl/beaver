import json
from pathlib import Path
import typer
import rich
import rich.table
from typing_extensions import Annotated
from typing import Optional

from beaver import BeaverDB

app = typer.Typer(
    name="blob",
    help="Interact with blob stores. (e.g., beaver blob assets put my-file.png /path/to/file.png)",
)


def _get_db(ctx: typer.Context) -> BeaverDB:
    """Helper to get the DB instance from the main context."""
    return ctx.find_object(dict)["db"]


def _parse_metadata(metadata_str: Optional[str]) -> Optional[dict]:
    """Parses the metadata string as JSON."""
    if metadata_str is None:
        return None
    if not (metadata_str.startswith("{") or metadata_str.startswith("[")):
        raise typer.BadParameter(
            'Metadata must be valid JSON (e.g., \'{"key":"value"}\')'
        )
    try:
        return json.loads(metadata_str)
    except json.JSONDecodeError:
        raise typer.BadParameter("Invalid JSON format for metadata.")


@app.callback(invoke_without_command=True)
def blob_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Argument(help="The name of the blob store to interact with."),
    ] = None,
):
    """
    Manage binary blob stores.

    If no name is provided, lists all available blob stores.
    """
    db = _get_db(ctx)

    if name is None:
        # No name given, so list all blob stores
        rich.print("[bold]Available Blob Stores:[/bold]")
        try:
            blob_names = db.blobs
            if not blob_names:
                rich.print("  (No blob stores found)")
            else:
                for blob_name in blob_names:
                    rich.print(f"  • {blob_name}")
            rich.print(
                "\n[bold]Usage:[/bold] beaver blob [bold]<NAME>[/bold] [COMMAND]"
            )
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying blob stores:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command
        try:
            count = len(db.blob(name))
            rich.print(f"Blob Store '[bold]{name}[/bold]' contains {count} items.")
            rich.print("\n[bold]Commands:[/bold]")
            rich.print("  put, get, del, list, dump")
            rich.print(
                f"\nRun [bold]beaver blob {name} --help[/bold] for command-specific options."
            )
        except Exception as e:
            rich.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1)
        raise typer.Exit()


@app.command()
def put(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="The unique key to store the blob under.")],
    file_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="The path to the file to upload.",
        ),
    ],
    metadata: Annotated[
        Optional[str], typer.Option(help="Optional metadata as a JSON string.")
    ] = None,
):
    """
    Put (upload) a file into the blob store.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_metadata = _parse_metadata(metadata)

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        db.blob(name).put(key, file_bytes, metadata=parsed_metadata)
        rich.print(
            f"[green]Success:[/] File '{file_path}' stored as key '{key}' in blob store '{name}'."
        )
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def get(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="The key of the blob to retrieve.")],
    output_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="The path to the file to upload.",
        ),
    ],
):
    """
    Get (download) a file from the blob store.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        blob = db.blob(name).get(key)
        if blob is None:
            rich.print(f"[bold red]Error:[/] Key not found: '{key}'")
            raise typer.Exit(code=1)

        with open(output_path, "wb") as f:
            f.write(blob.data)

        rich.print(f"[green]Success:[/] Blob '{key}' saved to '{output_path}'.")
        if blob.metadata:
            rich.print("[bold]Metadata:[/bold]")
            if isinstance(blob.metadata, (dict, list)):
                rich.print_json(data=blob.metadata)
            else:
                rich.print(str(blob.metadata))

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command(name="del")
def delete(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="The key of the blob to delete.")],
):
    """
    Delete a blob from the store.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        db.blob(name).delete(key)
        rich.print(f"[green]Success:[/] Blob '{key}' deleted from store '{name}'.")
    except KeyError:
        rich.print(f"[bold red]Error:[/] Key not found: '{key}'")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command(name="list")
def list_keys(ctx: typer.Context):
    """
    List all keys in the blob store.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        # The __iter__ for BlobManager yields keys
        all_keys = list(db.blob(name))
        if not all_keys:
            rich.print(f"Blob store '{name}' is empty.")
            return

        table = rich.table.Table(title=f"Keys in Blob Store: [bold]{name}[/bold]")
        table.add_column("Key")

        for key in all_keys:
            table.add_row(key)
        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def dump(ctx: typer.Context):
    """
    Dump the entire blob store as JSON (with data as base64).
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        dump_data = db.blob(name).dump()
        rich.print_json(data=dump_data)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
