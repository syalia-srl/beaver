import json
import typer
import rich
import rich.table
import statistics
import time
from collections import defaultdict
from datetime import timedelta
from typing_extensions import Annotated
from typing import Optional, List, Dict, Any
from rich.live import Live
from rich.table import Table

from beaver import BeaverDB

app = typer.Typer(
    name="log",
    help="Interact with time-indexed logs. (e.g., beaver log errors write '{\"code\": 500}')",
)

# --- Helper Functions ---


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


def _build_stats_aggregator(window: List[Dict[str, Any]]) -> dict:
    """
    The custom aggregator function.
    It processes a list of log entries and returns a stats summary.
    """
    total_count = len(window)
    # Use defaultdict to easily build nested stats
    key_stats = defaultdict(lambda: {"count": 0, "numeric_values": [], "types": set()})
    non_dict_count = 0

    for entry in window:
        if not isinstance(entry, dict):
            non_dict_count += 1
            continue  # Only aggregate stats for dict logs

        for key, value in entry.items():
            stats = key_stats[key]
            stats["count"] += 1
            stats["types"].add(type(value).__name__)
            if isinstance(value, (int, float)):
                stats["numeric_values"].append(value)

    # Finalize stats
    summary = {"total_count": total_count, "non_dict_count": non_dict_count, "keys": {}}
    for key, stats in sorted(key_stats.items()):
        key_summary = {"count": stats["count"], "types": sorted(list(stats["types"]))}
        if stats["numeric_values"]:
            key_summary["min"] = min(stats["numeric_values"])
            key_summary["max"] = max(stats["numeric_values"])
            key_summary["mean"] = statistics.mean(stats["numeric_values"])
        summary["keys"][key] = key_summary

    return summary


def _generate_stats_table(summary: dict, name: str, window_s: int) -> Table:
    """Builds a rich.Table object from the stats summary."""

    table = Table(title=f"Live Log Stats: [bold]{name}[/bold] ({window_s}s window)")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Count", style="magenta", justify="right")
    table.add_column("Types", style="green")
    table.add_column("Min", style="blue", justify="right")
    table.add_column("Max", style="blue", justify="right")
    table.add_column("Mean", style="blue", justify="right")

    for key, stats in summary.get("keys", {}).items():
        table.add_row(
            key,
            str(stats["count"]),
            ", ".join(stats["types"]),
            f"{stats.get('min', 'N/A'):.2f}" if "min" in stats else "N/A",
            f"{stats.get('max', 'N/A'):.2f}" if "max" in stats else "N/A",
            f"{stats.get('mean', 'N/A'):.2f}" if "mean" in stats else "N/A",
        )

    caption = f"Total Events: {summary['total_count']}"
    if summary["non_dict_count"] > 0:
        caption += f" ({summary['non_dict_count']} non-JSON-object events not shown)"
    table.caption = caption
    return table


# --- CLI Commands ---


@app.callback(invoke_without_command=True)
def log_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str], typer.Argument(help="The name of the log to interact with.")
    ] = None,
):
    """
    Manage time-indexed logs.

    If no name is provided, lists all available logs.
    """
    db = _get_db(ctx)

    if name is None:
        rich.print("[bold]Available Logs:[/bold]")
        try:
            log_names = db.logs
            if not log_names:
                rich.print("  (No logs found)")
            else:
                for log_name in log_names:
                    rich.print(f"  • {log_name}")
            rich.print("\n[bold]Usage:[/bold] beaver log [bold]<NAME>[/bold] [COMMAND]")
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying logs:[/] {e}")
            raise typer.Exit(code=1)

    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        rich.print(f"Log '[bold]{name}[/bold]'.")
        rich.print("\n[bold]Commands:[/bold]")
        rich.print("  write, watch")
        rich.print(
            f"\nRun [bold]beaver log {name} --help[/bold] for command-specific options."
        )
        raise typer.Exit()


@app.command()
def write(
    ctx: typer.Context,
    data: Annotated[
        str,
        typer.Argument(
            help="The data to log (e.g., '{\"a\": 1}', '\"my string\"', '123.45', 'true')."
        ),
    ],
):
    """
    Write a new data entry to the log.

    The data will be parsed as JSON, a number, a boolean, or a string.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_data = _parse_value(data)
        db.log(name).log(parsed_data)
        rich.print(f"[green]Success:[/] Log entry added to '{name}'.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def watch(
    ctx: typer.Context,
    window: Annotated[
        int, typer.Option("--window", help="Time window in seconds to aggregate over.")
    ] = 60,
    frequency: Annotated[
        int, typer.Option("--frequency", help="Time in seconds between updates.")
    ] = 1,
):
    """
    Watch a live, aggregated view of JSON log entries.

    This command only processes logs that are JSON objects and provides
    basic statistics for the keys found in those objects.
    """
    db: BeaverDB = ctx.obj["db"]
    name = ctx.obj["name"]

    try:
        log_manager = db.log(name)
        live_stream = log_manager.live(
            window=timedelta(seconds=window),
            period=timedelta(seconds=frequency),
            aggregator=_build_stats_aggregator,
        )

        rich.print(
            f"[cyan]Watching log '[bold]{name}[/bold]' (Window: {window}s, Freq: {frequency}s)... Press Ctrl+C to stop.[/cyan]"
        )

        # Use screen=True to create a new buffer and avoid flickering
        with Live(screen=True, refresh_per_second=4, transient=True) as live:
            for summary in live_stream:
                live.update(_generate_stats_table(summary, name, window))

    except KeyboardInterrupt:
        rich.print("\n[cyan]Stopping watcher...[/cyan]")
        raise typer.Exit()
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
