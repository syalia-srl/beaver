import typer
import rich
import subprocess
import threading
from typing_extensions import Annotated
from typing import Optional, List

from beaver import BeaverDB
from beaver.locks import LockManager

app = typer.Typer(
    name="lock",
    help="Run commands under lock or manage locks. (e.g., beaver lock my-lock run bash -c 'sleep 10')",
)


def _get_db(ctx: typer.Context) -> BeaverDB:
    """Helper to get the DB instance from the main context."""
    return ctx.find_object(dict)["db"]


@app.callback(invoke_without_command=True)
def lock_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str], typer.Argument(help="The unique name of the lock.")
    ] = None,
):
    """
    Manage and run commands under distributed locks.

    If no name is provided, lists all active locks.
    """
    db = _get_db(ctx)

    if name is None:
        # No name given, so list all active locks
        rich.print("[bold]Active Locks:[/bold]")
        try:
            lock_names = db.locks
            if not lock_names:
                rich.print("  (No active locks found)")
            else:
                for lock_name in lock_names:
                    rich.print(f"  • {lock_name}")
            rich.print(
                "\n[bold]Usage:[/bold] beaver lock [bold]<LOCK_NAME>[/bold] [COMMAND]"
            )
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying locks:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command
        rich.print(f"Lock '[bold]{name}[/bold]'.")
        rich.print("\n[bold]Commands:[/bold]")
        rich.print("  run, clear")
        rich.print(
            f"\nRun [bold]beaver lock {name} --help[/bold] for command-specific options."
        )
        raise typer.Exit()


def _heartbeat_task(lock: LockManager, ttl: float, stop_event: threading.Event):
    """
    A background task that periodically renews the lock.
    """
    # Renew at 50% of the TTL duration
    renew_interval = ttl / 2.0

    while not stop_event.wait(renew_interval):
        try:
            if not lock.renew(lock_ttl=ttl):
                # We lost the lock for some reason
                rich.print(
                    f"[bold red]Error:[/] Failed to renew lock '{lock._lock_name}'. Lock lost."
                )
                break
        except Exception as e:
            rich.print(f"[bold red]Heartbeat Error:[/] {e}")
            break


@app.command(
    "run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run_command(
    ctx: typer.Context,
    timeout: Annotated[
        Optional[float],
        typer.Option(
            help="Max seconds to wait for the lock. Waits forever by default."
        ),
    ] = None,
    ttl: Annotated[
        float, typer.Option(help="Seconds the lock can be held before auto-expiring.")
    ] = 60.0,
):
    """
    Run a command while holding the lock.

    This command will acquire the lock, run your command as a subprocess,
    and automatically renew the lock in the background until your command
    finishes.

    Example:

    beaver lock my-cron-job run bash -c 'run_daily_report.sh'
    """
    db: BeaverDB = ctx.obj["db"]
    name = ctx.obj["name"]
    command: List[str] = ctx.args

    if not command:
        rich.print("[bold red]Error:[/] No command provided to 'run'.")
        raise typer.Exit(code=1)

    lock = db.lock(name, timeout=timeout, ttl=ttl)
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_task, args=(lock, ttl, stop_heartbeat), daemon=True
    )

    process = None
    return_code = 1  # Default to error

    try:
        rich.print(
            f"[cyan]Waiting to acquire lock '[bold]{name}[/bold]' (Timeout: {timeout or 'inf'})...[/cyan]"
        )
        lock.acquire()
        rich.print(
            f"[green]Lock acquired. Running command:[/green] {' '.join(command)}"
        )

        # Start the heartbeat thread AFTER acquiring the lock
        heartbeat_thread.start()

        # Run the subprocess
        process = subprocess.Popen(command, shell=False)
        process.wait()
        return_code = process.returncode

        if return_code == 0:
            rich.print(f"[green]Command finished successfully.[/green]")
        else:
            rich.print(f"[bold red]Command failed with exit code {return_code}.[/bold]")

    except TimeoutError:
        rich.print(f"[bold yellow]Timeout:[/] Failed to acquire lock '{name}'.")
        raise typer.Exit(code=1)
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error:[/] Command not found: '{command[0]}'. Check your system's PATH."
        )
        raise typer.Exit(code=127)  # Standard exit code for "command not found"
    except KeyboardInterrupt:
        rich.print(
            "\n[bold yellow]Interrupted.[/bold] Releasing lock and stopping subprocess..."
        )
        if process:
            process.terminate()
            process.wait()
        return_code = 130  # Standard exit code for Ctrl+C
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
    finally:
        # Stop the heartbeat and release the lock
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1.0)  # Wait briefly for thread to stop
        lock.release()
        rich.print(f"Lock '[bold]{name}[/bold]' released.")

    if return_code != 0:
        raise typer.Exit(code=return_code)


@app.command("clear")
def clear(ctx: typer.Context):
    """
    Forcibly clear all waiters for the lock.

    This removes ALL entries for the lock, including the
    current holder and all waiting processes.
    """
    db: BeaverDB = ctx.obj["db"]
    name = ctx.obj["name"]

    try:
        # Use the static method from the core library
        if db.lock(name).clear():
            rich.print(f"[green]Success:[/] Cleared lock '[bold]{name}[/bold]'.")
        else:
            rich.print(f"[yellow]No waiter on lock[/] '[bold]{name}[/bold]'.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
