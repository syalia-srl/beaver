import asyncio
import sys
import time
import os
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeRemainingColumn,
    TaskProgressColumn,
)

from beaver import AsyncBeaverDB, Document

# Configuration
DB_PATH = "benchmark_vectors.db"
COLLECTION_NAME = "benchmark_1m"
NUM_VECTORS = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000  # Scale this up to 1_000_000 for full stress test
VECTOR_DIM = 128
SEARCH_QUERIES = 100
TOP_K = 10


async def main():
    console = Console()
    console.rule("[bold cyan]BeaverDB Vector Benchmark[/]")

    # 1. Setup
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    db = AsyncBeaverDB(DB_PATH)
    await db.connect()
    vectors = db.vectors(COLLECTION_NAME)

    try:
        # 2. Data Generation
        console.print(f"Generating {NUM_VECTORS} random vectors (dim={VECTOR_DIM})...")
        data = np.random.randn(NUM_VECTORS, VECTOR_DIM).astype(np.float32)
        # Normalize
        data /= np.linalg.norm(data, axis=1, keepdims=True)

        # 3. Ingestion
        console.print("\n[bold]Phase 1: Ingestion[/]")
        start_ingest = time.perf_counter()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("[green]Indexing vectors...", total=NUM_VECTORS)

            # Simple loop for now (until set_many is optimized)
            for i in range(NUM_VECTORS):
                await vectors.set(f"id_{i}", data[i].tolist())
                progress.advance(task)

        end_ingest = time.perf_counter()
        ingest_time = end_ingest - start_ingest
        console.print(
            f"✅ Ingestion complete: {ingest_time:.2f}s ({NUM_VECTORS / ingest_time:.0f} vectors/sec)"
        )

        # 2. Analyze Buckets
        console.print("Analyzing Bucket Distribution...")
        rows = await db.connection.execute_fetchall(
            "SELECT bucket_id, COUNT(*) as c FROM __beaver_lsh_index__ WHERE collection = ? GROUP BY bucket_id",
            (COLLECTION_NAME,),
        )

        counts = [r[1] for r in rows]
        total_buckets = len(counts)
        max_bucket = max(counts)
        avg_bucket = np.mean(counts)

        console.print(f"Total Buckets Used: {total_buckets} (out of 65536)")
        console.print(f"Max items in one bucket: {max_bucket}")
        console.print(f"Avg items per bucket: {avg_bucket:.2f}")

        # 4. Search Benchmark
        console.print("\n[bold]Phase 2: Search Performance[/]")

        # Generate Queries
        queries = np.random.randn(SEARCH_QUERIES, VECTOR_DIM).astype(np.float32)
        queries /= np.linalg.norm(queries, axis=1, keepdims=True)

        results_table = Table(title=f"Search Benchmark (Top-K={TOP_K})")
        results_table.add_column("Strategy", style="cyan")
        results_table.add_column("Total Time (s)", justify="right")
        results_table.add_column("Avg Latency (ms)", justify="right", style="yellow")
        results_table.add_column("QPS", justify="right", style="green")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            transient=True,
        ) as progress:
            # A. Exact Scan (Linear)
            task_exact = progress.add_task(
                "[cyan]Running Exact Scan...", total=SEARCH_QUERIES
            )
            start_exact = time.perf_counter()
            for i in range(SEARCH_QUERIES):
                await vectors.near(queries[i].tolist(), k=TOP_K, method="exact")
                progress.advance(task_exact)
            end_exact = time.perf_counter()

            time_exact = end_exact - start_exact
            avg_exact = (time_exact / SEARCH_QUERIES) * 1000
            qps_exact = SEARCH_QUERIES / time_exact

            results_table.add_row(
                "Exact (Linear Scan)",
                f"{time_exact:.4f}",
                f"{avg_exact:.2f}",
                f"{qps_exact:.0f}",
            )

            # B. LSH (Approximate)
            task_lsh = progress.add_task(
                "[magenta]Running LSH Search...", total=SEARCH_QUERIES
            )
            start_lsh = time.perf_counter()
            for i in range(SEARCH_QUERIES):
                await vectors.near(queries[i].tolist(), k=TOP_K, method="lsh")
                progress.advance(task_lsh)
            end_lsh = time.perf_counter()

            time_lsh = end_lsh - start_lsh
            avg_lsh = (time_lsh / SEARCH_QUERIES) * 1000
            qps_lsh = SEARCH_QUERIES / time_lsh

            results_table.add_row(
                "LSH (SimHash)", f"{time_lsh:.4f}", f"{avg_lsh:.2f}", f"{qps_lsh:.0f}"
            )

        console.print(results_table)

        # 5. Speedup Analysis
        if avg_lsh > 0:
            speedup = avg_exact / avg_lsh
            console.print(f"\n🚀 Speedup Factor: [bold green]{speedup:.2f}x[/]")

            if avg_lsh < avg_exact:
                console.print(
                    "[green]LSH is faster! The implementation is working effectively.[/]"
                )
            else:
                console.print(
                    "[yellow]LSH is slower. Dataset might be too small for index overhead to pay off.[/]"
                )

    finally:
        await db.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            # Cleanup WAL files if they exist
            if os.path.exists(f"{DB_PATH}-wal"):
                os.remove(f"{DB_PATH}-wal")
            if os.path.exists(f"{DB_PATH}-shm"):
                os.remove(f"{DB_PATH}-shm")


if __name__ == "__main__":
    asyncio.run(main())
