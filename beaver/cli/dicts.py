import json
import typer
import rich
from typing_extensions import Annotated
from typing import Optional

from beaver import BeaverDB

app = typer.Typer(
    name="dict",
    help="Interact with namespaced dictionaries. (e.g., beaver dict my-dict get my-key)",
)


def _parse_value(value: str):
    """Parses the value string as JSON if appropriate."""
    if value.startswith("{") or value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


@app.callback(invoke_without_command=True)
def dict_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Argument(help="The name of the dictionary to interact with."),
    ] = None,
):
    """
    Manage namespaced dictionaries.

    If no name is provided, lists all available dictionaries.
    """
    db = ctx.obj["db"]

    if db is None:
        rich.print(f"[bold red]Database not found![/]")
        return

    if name is None:
        # No name given, so list all dicts
        rich.print("[bold]Available Dictionaries:[/bold]")
        try:
            dict_names = db.dicts
            if not dict_names:
                rich.print("  (No dictionaries found)")
            else:
                for dict_name in dict_names:
                    rich.print(f"  • {dict_name}")
            rich.print(
                "\n[bold]Usage:[/bold] beaver dict [bold]<NAME>[/bold] [COMMAND]"
            )
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying dictionaries:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command (e.g., "beaver dict my-dict")
        rich.print(f"No command specified for dictionary '[bold]{name}[/bold]'.")
        rich.print("\n[bold]Commands:[/bold]")
        rich.print("  get, set, del, keys, dump")
        rich.print(
            f"\nRun [bold]beaver dict {name} --help[/bold] for command-specific options."
        )
        raise typer.Exit()


@app.command()
def get(
    ctx: typer.Context, key: Annotated[str, typer.Argument(help="The key to retrieve.")]
):
    """
    Get a value by key.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        value = db.dict(name).get(key)
        if value is None:
            rich.print(f"[bold red]Error:[/] Key not found: '{key}'")
            raise typer.Exit(code=1)

        if isinstance(value, (dict, list)):
            rich.print_json(data=value)
        else:
            rich.print(value)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def set(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="The key to set.")],
    value: Annotated[str, typer.Argument(help="The value (JSON or string).")],
):
    """
    Set a value for a key.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_value = _parse_value(value)
        db.dict(name)[key] = parsed_value
        rich.print(f"[green]Success:[/] Key '{key}' set in dictionary '{name}'.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command(name="del")
def delete(
    ctx: typer.Context, key: Annotated[str, typer.Argument(help="The key to delete.")]
):
    """
    Delete a key from the dictionary.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        del db.dict(name)[key]
        rich.print(f"[green]Success:[/] Key '{key}' deleted from dictionary '{name}'.")
    except KeyError:
        rich.print(f"[bold red]Error:[/] Key not found: '{key}'")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def keys(ctx: typer.Context):
    """
    List all keys in the dictionary.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        all_keys = list(db.dict(name).keys())
        if not all_keys:
            rich.print(f"Dictionary '{name}' is empty.")
            return
        for key in all_keys:
            rich.print(key)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def dump(ctx: typer.Context):
    """
    Dump the entire dictionary as JSON.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        dump_data = db.dict(name).dump()
        rich.print_json(data=dump_data)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
