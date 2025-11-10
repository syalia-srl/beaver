import json
import typer
import rich
import rich.table
from typing_extensions import Annotated
from typing import Optional

from beaver import BeaverDB

app = typer.Typer(
    name="list",
    help="Interact with persistent lists. (e.g., beaver list my-list push 'new item')",
)


def _get_db(ctx: typer.Context) -> BeaverDB:
    """Helper to get the DB instance from the main context."""
    return ctx.find_object(dict)["db"]


def _parse_value(value: str):
    """Parses the value string as JSON if appropriate."""
    if value.startswith("{") or value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


@app.callback(invoke_without_command=True)
def list_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str], typer.Argument(help="The name of the list to interact with.")
    ] = None,
):
    """
    Manage persistent lists.

    If no name is provided, lists all available lists.
    """
    db = _get_db(ctx)

    if name is None:
        # No name given, so list all lists
        rich.print("[bold]Available Lists:[/bold]")
        try:
            list_names = db.lists
            if not list_names:
                rich.print("  (No lists found)")
            else:
                for list_name in list_names:
                    rich.print(f"  • {list_name}")
            rich.print(
                "\n[bold]Usage:[/bold] beaver list [bold]<NAME>[/bold] [COMMAND]"
            )
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying lists:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command
        try:
            count = len(db.list(name))
            rich.print(f"List '[bold]{name}[/bold]' contains {count} items.")
            rich.print("\n[bold]Commands:[/bold]")
            rich.print("  push, pop, deque, insert, remove, items, dump")
            rich.print(
                f"\nRun [bold]beaver list {name} --help[/bold] for command-specific options."
            )
        except Exception as e:
            rich.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1)
        raise typer.Exit()


@app.command()
def push(
    ctx: typer.Context,
    value: Annotated[str, typer.Argument(help="The value to add (JSON or string).")],
):
    """
    Add (push) an item to the end of the list.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_value = _parse_value(value)
        db.list(name).push(parsed_value)
        rich.print(f"[green]Success:[/] Item pushed to list '{name}'.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def pop(ctx: typer.Context):
    """
    Remove and return the last item from the list.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        item = db.list(name).pop()
        if item is None:
            rich.print(f"List '{name}' is empty.")
            return

        rich.print("[green]Popped item:[/green]")
        if isinstance(item, (dict, list)):
            rich.print_json(data=item)
        else:
            rich.print(item)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def deque(ctx: typer.Context):
    """
    Remove and return the first item from the list.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        item = db.list(name).deque()
        if item is None:
            rich.print(f"List '{name}' is empty.")
            return

        rich.print("[green]Dequeued item:[/green]")
        if isinstance(item, (dict, list)):
            rich.print_json(data=item)
        else:
            rich.print(item)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def insert(
    ctx: typer.Context,
    index: Annotated[
        int, typer.Argument(help="The index to insert at (e.g., 0 for front).")
    ],
    value: Annotated[str, typer.Argument(help="The value to insert (JSON or string).")],
):
    """
    Insert an item at a specific index.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_value = _parse_value(value)
        db.list(name).insert(index, parsed_value)
        rich.print(
            f"[green]Success:[/] Item inserted at index {index} in list '{name}'."
        )
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def remove(
    ctx: typer.Context,
    index: Annotated[int, typer.Argument(help="The index of the item to remove.")],
):
    """
    Remove and return an item from a specific index.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        # Get the item before deleting it to print it
        item = db.list(name)[index]
        del db.list(name)[index]

        rich.print(f"[green]Success:[/] Removed item from index {index}:")
        if isinstance(item, (dict, list)):
            rich.print_json(data=item)
        else:
            rich.print(item)

    except IndexError:
        rich.print(f"[bold red]Error:[/] Index {index} out of range for list '{name}'.")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def items(ctx: typer.Context):
    """
    Print all items in the list, in order.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        # `[:]` is the slice syntax to get all items from ListManager
        all_items = db.list(name)[:]
        if not all_items:
            rich.print(f"List '{name}' is empty.")
            return

        table = rich.table.Table(title=f"Items in List: [bold]{name}[/bold]")
        table.add_column("Index", style="cyan", justify="right")
        table.add_column("Value")

        for i, item in enumerate(all_items):
            if isinstance(item, (dict, list)):
                table.add_row(str(i), json.dumps(item))
            else:
                table.add_row(str(i), str(item))
        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def dump(ctx: typer.Context):
    """
    Dump the entire list as JSON.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        dump_data = db.list(name).dump()
        rich.print_json(data=dump_data)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
