import json
import typer
import rich
import rich.table
from typing_extensions import Annotated
from typing import Optional

from beaver import BeaverDB

app = typer.Typer(
    name="queue",
    help="Interact with persistent priority queues. (e.g., beaver queue my-tasks put 1 'new task')"
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
def queue_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Argument(help="The name of the queue to interact with.")
    ] = None
):
    """
    Manage persistent priority queues.

    If no name is provided, lists all available queues.
    """
    db = _get_db(ctx)

    if name is None:
        # No name given, so list all queues
        rich.print("[bold]Available Queues:[/bold]")
        try:
            queue_names = db.queues
            if not queue_names:
                rich.print("  (No queues found)")
            else:
                for queue_name in queue_names:
                    rich.print(f"  • {queue_name}")
            rich.print("\n[bold]Usage:[/bold] beaver queue [bold]<NAME>[/bold] [COMMAND]")
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying queues:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command
        try:
            count = len(db.queue(name))
            rich.print(f"Queue '[bold]{name}[/bold]' contains {count} items.")
            rich.print("\n[bold]Commands:[/bold]")
            rich.print("  put, get, peek, show, dump")
            rich.print(f"\nRun [bold]beaver queue {name} --help[/bold] for command-specific options.")
        except Exception as e:
            rich.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1)
        raise typer.Exit()

@app.command()
def put(
    ctx: typer.Context,
    priority: Annotated[float, typer.Argument(help="The item priority (float). Lower is higher priority.")],
    value: Annotated[str, typer.Argument(help="The value to add (JSON or string).")]
):
    """
    Add (put) an item into the queue with a specific priority.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_value = _parse_value(value)
        db.queue(name).put(parsed_value, priority=priority)
        rich.print(f"[green]Success:[/] Item added to queue '{name}' with priority {priority}.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def get(
    ctx: typer.Context,
    block: Annotated[bool, typer.Option("--block/--no-block", help="Block until an item is available.")] = True,
    timeout: Annotated[Optional[float], typer.Option(help="Max seconds to block. Requires --block.")] = 5.0
):
    """
    Get and remove the highest-priority item from the queue.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        if block:
            rich.print(f"Waiting for item from '{name}' (timeout={timeout}s)...")

        item = db.queue(name).get(block=block, timeout=timeout)

        rich.print(f"[green]Got item (Priority: {item.priority}):[/green]")
        if isinstance(item.data, (dict, list)):
            rich.print_json(data=item.data)
        else:
            rich.print(item.data)

    except IndexError:
        rich.print(f"Queue '{name}' is empty (non-blocking get).")
    except TimeoutError:
        rich.print(f"[bold yellow]Timeout:[/] No item received from queue '{name}' after {timeout}s.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def peek(ctx: typer.Context):
    """
    View the highest-priority item without removing it.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        item = db.queue(name).peek()
        if item is None:
            rich.print(f"Queue '{name}' is empty.")
            return

        rich.print(f"[green]Next item (Priority: {item.priority}):[/green]")
        if isinstance(item.data, (dict, list)):
            rich.print_json(data=item.data)
        else:
            rich.print(item.data)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def show(ctx: typer.Context):
    """
    Print all items in the queue, in priority order.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        # The __iter__ for QueueManager yields all items in order
        all_items = list(db.queue(name))
        if not all_items:
            rich.print(f"Queue '{name}' is empty.")
            return

        table = rich.table.Table(title=f"Items in Queue: [bold]{name}[/bold]")
        table.add_column("Priority", style="cyan", justify="right")
        table.add_column("Timestamp", style="magenta")
        table.add_column("Data")

        for item in all_items:
            data_str = json.dumps(item.data) if isinstance(item.data, (dict, list)) else str(item.data)
            table.add_row(str(item.priority), str(item.timestamp), data_str)
        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def dump(ctx: typer.Context):
    """
    Dump the entire queue as JSON.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        dump_data = db.queue(name).dump()
        rich.print_json(data=dump_data)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
