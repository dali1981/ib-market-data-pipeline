#!/usr/bin/env python
"""
Migrate existing Parquet data to Delta Lake format.

This script reads existing Parquet files from dlt-ibapi's data directory
and writes them to Delta Lake format, preserving all partition structure.

Usage:
    # Preview migration (dry-run)
    uv run python scripts/migration/migrate_to_delta.py --dry-run

    # Migrate specific dataset
    uv run python scripts/migration/migrate_to_delta.py --dataset stocks

    # Migrate all datasets
    uv run python scripts/migration/migrate_to_delta.py --all

    # Use custom output location
    uv run python scripts/migration/migrate_to_delta.py --all --output s3://ibapi-data/warehouse

    # Keep original Parquet files after migration
    uv run python scripts/migration/migrate_to_delta.py --all --no-delete
"""

import sys
from pathlib import Path
from typing import Optional, List
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from delta_lake_storage import get_config, StorageBackend
from delta_lake_storage.backends import FilesystemBackend, DeltaLakeBackend

app = typer.Typer(help="Migrate Parquet data to Delta Lake format")
console = Console()


def get_datasets(data_path: Path) -> List[str]:
    """Get list of datasets in data directory."""
    if not data_path.exists():
        return []

    return [d.name for d in data_path.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]


def get_tables(dataset_path: Path) -> List[str]:
    """Get list of tables in dataset."""
    if not dataset_path.exists():
        return []

    tables = []
    for item in dataset_path.iterdir():
        if item.is_dir() and not item.name.startswith((".", "_")):
            # Check if it contains Parquet files
            if any(item.rglob("*.parquet")):
                tables.append(item.name)

    return tables


@app.command()
def migrate(
    dataset: Optional[str] = typer.Option(None, "--dataset", "-d", help="Dataset to migrate (e.g., stocks, options)"),
    all_datasets: bool = typer.Option(False, "--all", "-a", help="Migrate all datasets"),
    source: Path = typer.Option(Path("./data"), "--source", "-s", help="Source data directory (Parquet)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output location (default: ./data_delta)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be migrated without doing it"),
    no_delete: bool = typer.Option(False, "--no-delete", help="Keep original Parquet files after migration"),
):
    """
    Migrate Parquet data to Delta Lake format.

    Examples:
        # Preview migration
        uv run python scripts/migration/migrate_to_delta.py --dry-run --all

        # Migrate stocks dataset
        uv run python scripts/migration/migrate_to_delta.py --dataset stocks

        # Migrate all to S3/MinIO
        uv run python scripts/migration/migrate_to_delta.py --all --output s3://ibapi-data/warehouse
    """
    console.print("\n[bold cyan]Delta Lake Migration Tool[/bold cyan]\n")

    # Validate inputs
    if not dataset and not all_datasets:
        console.print("[red]❌ Error: Must specify --dataset or --all[/red]")
        raise typer.Exit(1)

    if not source.exists():
        console.print(f"[red]❌ Error: Source directory not found: {source}[/red]")
        raise typer.Exit(1)

    # Determine output location
    if output is None:
        output_path = "./data_delta"
    else:
        output_path = output

    # Get datasets to migrate
    if all_datasets:
        datasets = get_datasets(source)
        if not datasets:
            console.print(f"[yellow]⚠ No datasets found in {source}[/yellow]")
            raise typer.Exit(0)
    else:
        datasets = [dataset]

    console.print(f"Source:  {source}")
    console.print(f"Output:  {output_path}")
    console.print(f"Mode:    {'DRY RUN' if dry_run else 'LIVE MIGRATION'}")
    console.print(f"Delete:  {'No (keep originals)' if no_delete else 'Yes (delete after migration)'}\n")

    # Scan datasets
    migration_plan = []
    for ds in datasets:
        dataset_path = source / ds
        if not dataset_path.exists():
            console.print(f"[yellow]⚠ Dataset not found: {ds}[/yellow]")
            continue

        tables = get_tables(dataset_path)
        for table in tables:
            table_path = dataset_path / table
            parquet_files = list(table_path.rglob("*.parquet"))
            total_size = sum(f.stat().st_size for f in parquet_files)

            migration_plan.append({
                "dataset": ds,
                "table": table,
                "files": len(parquet_files),
                "size_mb": total_size / (1024 * 1024),
                "source_path": str(table_path),
                "target_path": f"{output_path}/{ds}/{table}",
            })

    if not migration_plan:
        console.print("[yellow]⚠ No data to migrate[/yellow]")
        raise typer.Exit(0)

    # Display migration plan
    table = Table(title="Migration Plan")
    table.add_column("Dataset", style="cyan")
    table.add_column("Table", style="green")
    table.add_column("Files", justify="right")
    table.add_column("Size (MB)", justify="right")

    total_files = 0
    total_size = 0
    for item in migration_plan:
        table.add_row(
            item["dataset"],
            item["table"],
            str(item["files"]),
            f"{item['size_mb']:.2f}",
        )
        total_files += item["files"]
        total_size += item["size_mb"]

    console.print(table)
    console.print(f"\n[bold]Total: {len(migration_plan)} tables, {total_files} files, {total_size:.2f} MB[/bold]\n")

    if dry_run:
        console.print("[yellow]DRY RUN: No changes made[/yellow]")
        return

    # Confirm migration
    if not typer.confirm("Proceed with migration?"):
        console.print("Migration cancelled")
        raise typer.Exit(0)

    # Perform migration
    console.print("\n[bold green]Starting migration...[/bold green]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        main_task = progress.add_task("Migrating...", total=len(migration_plan))

        for item in migration_plan:
            progress.update(main_task, description=f"Migrating {item['dataset']}.{item['table']}")

            try:
                # Read Parquet
                import pandas as pd
                import pyarrow.parquet as pq
                import pyarrow.dataset as ds
                from pathlib import Path

                # Filter to only .parquet files (skip .jsonl.gz and other files)
                table_path = Path(item["source_path"])
                parquet_files = [str(f) for f in table_path.rglob("*.parquet")]

                if not parquet_files:
                    console.print(f"  [yellow]⊘ {item['dataset']}.{item['table']}: No Parquet files found[/yellow]")
                    progress.advance(main_task)
                    continue

                dataset_reader = ds.dataset(parquet_files, format="parquet")
                table = dataset_reader.to_table()

                # Skip empty tables
                if len(table) == 0:
                    console.print(f"  [yellow]⊘ {item['dataset']}.{item['table']}: Empty table (skipped)[/yellow]")
                    progress.advance(main_task)
                    continue

                data = table.to_pandas()

                # Write to Delta Lake
                from deltalake import write_deltalake

                # Determine partition columns from source
                partition_cols = []
                if "date" in data.columns:
                    partition_cols.append("date")
                if "symbol" in data.columns:
                    partition_cols.append("symbol")

                write_deltalake(
                    item["target_path"],
                    data,
                    mode="overwrite",
                    partition_by=partition_cols if partition_cols else None,
                )

                console.print(f"  ✓ {item['dataset']}.{item['table']} → Delta Lake ({len(data)} rows)")

            except Exception as e:
                console.print(f"  [red]✗ {item['dataset']}.{item['table']}: {e}[/red]")

            progress.advance(main_task)

    console.print("\n[bold green]✓ Migration complete![/bold green]")

    if not no_delete:
        console.print("\n[yellow]⚠ Original Parquet files not deleted (use --no-delete=false to enable)[/yellow]")


@app.command()
def verify(
    dataset: str = typer.Argument(..., help="Dataset to verify"),
    table: str = typer.Argument(..., help="Table to verify"),
    delta_path: Path = typer.Option(Path("./data_delta"), "--delta-path", help="Delta Lake data directory"),
    parquet_path: Path = typer.Option(Path("./data"), "--parquet-path", help="Original Parquet directory"),
):
    """
    Verify migrated Delta table matches original Parquet data.

    Example:
        uv run python scripts/migration/migrate_to_delta.py verify stocks historical_bars
    """
    console.print("\n[bold cyan]Delta Lake Verification[/bold cyan]\n")

    delta_table_path = delta_path / dataset / table
    parquet_table_path = parquet_path / dataset / table

    if not delta_table_path.exists():
        console.print(f"[red]❌ Delta table not found: {delta_table_path}[/red]")
        raise typer.Exit(1)

    if not parquet_table_path.exists():
        console.print(f"[red]❌ Parquet table not found: {parquet_table_path}[/red]")
        raise typer.Exit(1)

    console.print(f"Verifying: {dataset}.{table}\n")

    try:
        import pandas as pd
        import pyarrow.dataset as ds
        from deltalake import DeltaTable

        # Read Parquet
        parquet_dataset = ds.dataset(str(parquet_table_path), format="parquet", partitioning="hive")
        parquet_data = parquet_dataset.to_table().to_pandas()

        # Read Delta
        delta_table = DeltaTable(str(delta_table_path))
        delta_data = delta_table.to_pandas()

        # Compare
        parquet_rows = len(parquet_data)
        delta_rows = len(delta_data)

        console.print(f"Parquet rows: {parquet_rows}")
        console.print(f"Delta rows:   {delta_rows}")

        if parquet_rows == delta_rows:
            console.print("\n[green]✓ Row counts match![/green]")
        else:
            console.print(f"\n[red]✗ Row count mismatch: {abs(parquet_rows - delta_rows)} rows different[/red]")
            raise typer.Exit(1)

        # Compare schemas
        parquet_cols = set(parquet_data.columns)
        delta_cols = set(delta_data.columns)

        if parquet_cols == delta_cols:
            console.print("[green]✓ Schemas match![/green]")
        else:
            missing = parquet_cols - delta_cols
            extra = delta_cols - parquet_cols
            if missing:
                console.print(f"[red]✗ Missing columns in Delta: {missing}[/red]")
            if extra:
                console.print(f"[yellow]⚠ Extra columns in Delta: {extra}[/yellow]")
            raise typer.Exit(1)

        console.print("\n[bold green]✓ Verification passed![/bold green]")

    except Exception as e:
        console.print(f"\n[red]✗ Verification failed: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
