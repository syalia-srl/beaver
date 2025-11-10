import json
import typer
import rich
from typing_extensions import Annotated
from typing import Optional
from datetime import datetime

from beaver import BeaverDB

app = typer.Typer(
    name="channel",
    help="Interact with pub/sub channels. (e.g., beaver channel events publish 'msg')",
)


def _get_db(ctx: typer.Context) -> BeaverDB:
    """Helper to get the DB instance from the main context."""
    return ctx.find_object(dict)["db"]


def _parse_value(value: str):
    """
    Intelligently parses the input string.
    - Tries to parse as JSON if it starts with '{' or '['.
    - Tries to parse as int, then float.
    - Checks for 'true'/'false'/'null'.
    - Defaults to a plain string.
    """
    # 1. Try JSON object or array
    if value.startswith("{") or value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # It's not valid JSON, so treat it as a string
            return value

    # 2. Try boolean
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False

    # 3. Try null
    if value.lower() == "null":
        return None

    # 4. Try int
    try:
        return int(value)
    except ValueError:
        pass

    # 5. Try float
    try:
        return float(value)
    except ValueError:
        pass

    # 6. Default to string (remove quotes if user added them)
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    return value


@app.callback(invoke_without_command=True)
def channel_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str], typer.Argument(help="The name of the channel to interact with.")
    ] = None,
):
    """
    Manage pub/sub channels.

    If no name is provided, lists all channels that have a message history.
    """
    db = _get_db(ctx)

    if name is None:
        # No name given, so list all channels
        rich.print("[bold]Available Channels (with history):[/bold]")
        try:
            channel_names = db.channels
            if not channel_names:
                rich.print("  (No channels with messages found in log)")
            else:
                for channel_name in channel_names:
                    rich.print(f"  • {channel_name}")
            rich.print(
                "\n[bold]Usage:[/bold] beaver channel [bold]<NAME>[/bold] [COMMAND]"
            )
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying channels:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command
        rich.print(f"Channel '[bold]{name}[/bold]'.")
        rich.print("\n[bold]Commands:[/bold]")
        rich.print("  publish, listen")
        rich.print(
            f"\nRun [bold]beaver channel {name} --help[/bold] for command-specific options."
        )
        raise typer.Exit()


@app.command()
def publish(
    ctx: typer.Context,
    message: Annotated[
        str, typer.Argument(help="The message to publish (JSON, string, number, etc.).")
    ],
):
    """
    Publish a message to the channel.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_message = _parse_value(message)
        db.channel(name).publish(parsed_message)
        rich.print(f"[green]Success:[/] Message published to channel '{name}'.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def listen(ctx: typer.Context):
    """
    Listen for new messages on the channel in real-time.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]

    rich.print(
        f"[cyan]Listening to channel '[bold]{name}[/bold]'... Press Ctrl+C to stop.[/cyan]"
    )

    try:
        with db.channel(name).subscribe() as listener:
            for message in listener.listen():
                now = datetime.now().strftime("%H:%M:%S")

                if isinstance(message, (dict, list)):
                    message_str = json.dumps(message)
                    rich.print(
                        f"[dim]{now}[/dim] [bold yellow]►[/bold yellow] {message_str}"
                    )
                else:
                    message_str = str(message)
                    rich.print(
                        f"[dim]{now}[/dim] [bold yellow]►[/bold yellow] {message_str}"
                    )

    except KeyboardInterrupt:
        rich.print("\n[cyan]Stopping listener...[/cyan]")
        raise typer.Exit()
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
