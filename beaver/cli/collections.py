import json
import os
import typer
import rich
import rich.table
from typing_extensions import Annotated
from typing import Optional, List, Any

# Import Document and WalkDirection for graph commands
from beaver import BeaverDB, Document, WalkDirection

app = typer.Typer(
    name="collection",
    help="Interact with document collections (vector, text, graph). (e.g., beaver collection articles match 'python')"
)

# --- Helper Functions ---

def _get_db(ctx: typer.Context) -> BeaverDB:
    """Helper to get the DB instance from the main context."""
    return ctx.find_object(dict)["db"]

def _parse_json_or_file(input_str: str) -> Any:
    """
    Tries to read as a file path. If that fails, tries to parse as JSON.
    If both fail, raises an error.
    """
    try:
        if os.path.exists(input_str):
            with open(input_str, 'r') as f:
                return json.load(f)
    except Exception:
        pass # Not a valid file path, or can't be read

    # Not a file, try to parse as JSON string
    try:
        return json.loads(input_str)
    except json.JSONDecodeError:
        # Re-try by wrapping in quotes, in case it's a plain string
        try:
            return json.loads(f'"{input_str}"')
        except json.JSONDecodeError:
             raise typer.BadParameter(
                f"Input '{input_str}' is not a valid file path or a valid JSON string."
            )

def _truncate(text: str, length: int = 100) -> str:
    """Truncates a string and adds an ellipsis if needed."""
    if len(text) > length:
        return text[:length] + "..."
    return text

# --- Main Callback and Commands ---

@app.callback(invoke_without_command=True)
def collection_main(
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Argument(help="The name of the collection to interact with.")
    ] = None
):
    """
    Manage document collections.

    If no name is provided, lists all available collections.
    """
    db = _get_db(ctx)

    if name is None:
        # No name given, so list all collections
        rich.print("[bold]Available Collections:[/bold]")
        try:
            collection_names = db.collections
            if not collection_names:
                rich.print("  (No collections found)")
            else:
                for col_name in collection_names:
                    rich.print(f"  • {col_name}")
            rich.print("\n[bold]Usage:[/bold] beaver collection [bold]<NAME>[/bold] [COMMAND]")
            return
        except Exception as e:
            rich.print(f"[bold red]Error querying collections:[/] {e}")
            raise typer.Exit(code=1)

    # A name was provided, store it in the context for subcommands
    ctx.obj = {"name": name, "db": db}

    if ctx.invoked_subcommand is None:
        # A name was given, but no command
        try:
            count = len(db.collection(name))
            rich.print(f"Collection '[bold]{name}[/bold]' contains {count} documents.")
            rich.print("\n[bold]Commands:[/bold]")
            rich.print("  get, index, drop, items, match, search, connect, neighboors, walk, dump")
            rich.print(f"\nRun [bold]beaver collection {name} --help[/bold] for command-specific options.")
        except Exception as e:
            rich.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1)
        raise typer.Exit()

@app.command()
def get(
    ctx: typer.Context,
    doc_id: Annotated[str, typer.Argument(help="The ID of the document to retrieve.")]
):
    """
    Get and print a single document by its ID.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        # The CollectionManager doesn't have a .get(), so we query manually.
        cursor = db.connection.cursor()
        cursor.execute(
            "SELECT item_id, item_vector, metadata FROM beaver_collections WHERE collection = ? AND item_id = ?",
            (name, doc_id),
        )
        row = cursor.fetchone()
        cursor.close()

        if row is None:
            rich.print(f"[bold red]Error:[/] Document not found: '{doc_id}'")
            raise typer.Exit(code=1)

        # Reconstruct the full document for printing
        doc_data = json.loads(row["metadata"])
        doc_data["id"] = row["item_id"]

        # Handle vector decoding if numpy is available
        try:
            import numpy as np
            doc_data["embedding"] = (
                list(map(float, np.frombuffer(row["item_vector"], dtype=np.float32)))
                if row["item_vector"]
                else None
            )
        except ImportError:
            doc_data["embedding"] = "N/A (requires numpy)"

        rich.print_json(data=doc_data)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def index(
    ctx: typer.Context,
    json_or_file: Annotated[str, typer.Argument(help="A JSON string or a file path to a JSON file.")],
    fts_on: Annotated[Optional[str], typer.Option("--fts", help="Comma-separated list of fields for FTS (e.g., 'title,body'). Default: all string fields.")] = None,
    no_fts: Annotated[bool, typer.Option("--no-fts", help="Disable FTS indexing for this document.")] = False,
    fuzzy: Annotated[bool, typer.Option("--fuzzy/--no-fuzzy", help="Enable fuzzy search indexing.")] = False
):
    """
    Index a new document from a JSON string or file.

    The JSON object's top-level 'id' and 'embedding' keys are used for the
    document ID and vector. All other keys are stored as metadata.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        doc_dict = _parse_json_or_file(json_or_file)
        if not isinstance(doc_dict, dict):
            raise typer.BadParameter("Input must be a JSON object (a dictionary).")

        doc_id = doc_dict.pop('id', None)
        doc_embedding = doc_dict.pop('embedding', None)

        # The rest of the dict is metadata
        doc = Document(id=doc_id, embedding=doc_embedding, **doc_dict)

        # Determine FTS argument
        if no_fts:
            fts_arg = False
        elif fts_on:
            fts_arg = fts_on.split(',')
        else:
            fts_arg = True

        db.collection(name).index(doc, fts=fts_arg, fuzzy=fuzzy)
        rich.print(f"[green]Success:[/] Document indexed with ID: [bold]{doc.id}[/bold]")

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command(name="drop")
def drop_doc(
    ctx: typer.Context,
    doc_id: Annotated[str, typer.Argument(help="The ID of the document to delete.")]
):
    """
    Delete a document from the collection by its ID.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        db.collection(name).drop(Document(id=doc_id))
        rich.print(f"[green]Success:[/] Document '{doc_id}' dropped from collection '{name}'.")
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def items(ctx: typer.Context):
    """
    List all items in the collection.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        all_items = list(db.collection(name))
        if not all_items:
            rich.print(f"Collection '{name}' is empty.")
            return

        table = rich.table.Table(title=f"Documents in Collection: [bold]{name}[/bold]")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Embedding", style="magenta", justify="center")
        table.add_column("Metadata (Summary)")

        for doc in all_items:
            metadata_dict = doc.to_dict() # This returns only metadata
            metadata_str = json.dumps(metadata_dict)
            embedding_str = f"{len(doc.embedding)}d" if doc.embedding is not None else "None"
            table.add_row(doc.id, embedding_str, _truncate(metadata_str))

        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def match(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="The search query text.")],
    on: Annotated[Optional[str], typer.Option(help="Comma-separated list of fields to search (e.g., 'title,body').")] = None,
    fuzziness: Annotated[int, typer.Option(help="Fuzziness level (0=exact, 1-2=typos).")] = 0,
    top_k: Annotated[int, typer.Option("--k", help="Number of results to return.")] = 5
):
    """
    Perform a full-text (or fuzzy) search.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        on_list = on.split(',') if on else None
        results = db.collection(name).match(query, on=on_list, top_k=top_k, fuzziness=fuzziness)

        if not results:
            rich.print("No results found.")
            return

        score_title = "Distance" if fuzziness > 0 else "Rank"
        table = rich.table.Table(title=f"Search Results for: [bold]'{query}'[/bold]")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column(score_title, style="magenta", justify="right")
        table.add_column("Metadata (Summary)")

        for doc, score in results:
            metadata_str = json.dumps(doc.to_dict())
            table.add_row(doc.id, f"{score:.4f}", _truncate(metadata_str))

        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def search(
    ctx: typer.Context,
    vector_json: Annotated[str, typer.Argument(help="The query vector as a JSON list (e.g., '[0.1, 0.2]').")],
    top_k: Annotated[int, typer.Option("--k", help="Number of results to return.")] = 5
):
    """
    Perform an approximate nearest neighbor (vector) search.
    Requires 'beaver-db[vector]' to be installed.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        vector_list = _parse_json_or_file(vector_json)
        if not isinstance(vector_list, list):
            raise typer.BadParameter("Input must be a JSON list (e.g., '[0.1, 0.2, 0.3]').")

        results = db.collection(name).search(vector_list, top_k=top_k)

        if not results:
            rich.print("No results found.")
            return

        table = rich.table.Table(title="Vector Search Results")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Distance", style="magenta", justify="right")
        table.add_column("Metadata (Summary)")

        for doc, distance in results:
            metadata_str = json.dumps(doc.to_dict())
            table.add_row(doc.id, f"{distance:.4f}", _truncate(metadata_str))

        rich.print(table)

    except ImportError:
        rich.print("[bold red]Error:[/] Vector search requires 'beaver-db[vector]'.")
        rich.print('Please install it with: pip install "beaver-db[vector]"')
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def connect(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="The ID of the source document.")],
    target_id: Annotated[str, typer.Argument(help="The ID of the target document.")],
    label: Annotated[str, typer.Argument(help="The label for the relationship (e.g., 'FOLLOWS').")],
    metadata: Annotated[Optional[str], typer.Option(help="Optional metadata as a JSON string.")] = None
):
    """
    Connect two documents with a directed, labeled relationship.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        parsed_metadata = _parse_json_or_file(metadata) if metadata else None
        source_doc = Document(id=source_id)
        target_doc = Document(id=target_id)

        db.collection(name).connect(source_doc, target_doc, label, metadata=parsed_metadata)
        rich.print(f"[green]Success:[/] Connected '{source_id}' -> '{target_id}' with label '{label}'.")

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def neighbors(
    ctx: typer.Context,
    doc_id: Annotated[str, typer.Argument(help="The ID of the source document.")],
    label: Annotated[Optional[str], typer.Option(help="Filter by edge label (e.g., 'FOLLOWS').")] = None
):
    """
    Find the 1-hop outgoing neighbors of a document.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        source_doc = Document(id=doc_id)
        results = db.collection(name).neighbors(source_doc, label=label)

        if not results:
            rich.print(f"No neighbors found for '{doc_id}'" + (f" with label '{label}'." if label else "."))
            return

        table = rich.table.Table(title=f"Neighbors of: [bold]'{doc_id}'[/bold]")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Metadata (Summary)")

        for doc in results:
            metadata_str = json.dumps(doc.to_dict())
            table.add_row(doc.id, _truncate(metadata_str))

        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def walk(
    ctx: typer.Context,
    doc_id: Annotated[str, typer.Argument(help="The ID of the starting document.")],
    labels: Annotated[str, typer.Option(help="Comma-separated list of labels to follow (e.g., 'FOLLOWS,MENTIONS').")],
    depth: Annotated[int, typer.Option(help="How many steps to walk.")] = 1,
    direction: Annotated[WalkDirection, typer.Option(case_sensitive=False, help="Direction of the walk.")] = WalkDirection.OUTGOING
):
    """
    Perform a multi-hop graph walk (BFS) from a document.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        source_doc = Document(id=doc_id)
        label_list = labels.split(',')

        results = db.collection(name).walk(
            source=source_doc,
            labels=label_list,
            depth=depth,
            direction=direction
        )

        if not results:
            rich.print(f"No results found for walk from '{doc_id}'.")
            return

        table = rich.table.Table(title=f"Walk Results from: [bold]'{doc_id}'[/bold] (Depth: {depth})")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Metadata (Summary)")

        for doc in results:
            metadata_str = json.dumps(doc.to_dict())
            table.add_row(doc.id, _truncate(metadata_str))

        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

@app.command()
def dump(ctx: typer.Context):
    """
    Dump the entire collection as JSON.
    """
    db = ctx.obj["db"]
    name = ctx.obj["name"]
    try:
        dump_data = db.collection(name).dump()
        rich.print_json(data=dump_data)
    except Exception as e:
        rich.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)
