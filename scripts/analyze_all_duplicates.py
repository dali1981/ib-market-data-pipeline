#!/usr/bin/env python3
"""
Analyze all datasets for duplicate records.

Generates a comprehensive report showing duplicate statistics across
all datasets and tables. Use this before running deduplication to
understand the scope of the cleanup operation.

Usage:
    uv run python scripts/analyze_all_duplicates.py
    uv run python scripts/analyze_all_duplicates.py --data-dir ./data_delta
    uv run python scripts/analyze_all_duplicates.py --output report.txt
"""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from dlt_ibapi.maintenance import get_duplicate_report


# Dataset configurations: (dataset_name, [(table_name, primary_key), ...])
DATASET_CONFIGS = {
    "options": [
        ("option_bars_backfill", ["underlying", "expiry", "strike", "right", "bar_size", "time"]),
        ("option_chain_snapshot", ["underlying", "as_of", "exchange", "trading_class"]),
    ],
    "stocks": [
        ("historical_bars", ["symbol", "bar_size", "time"]),
    ],
    "earnings": [
        ("earnings_calendar", ["symbol", "earnings_date"]),
    ],
    "option_chains": [
        ("option_chain_snapshot", ["underlying", "as_of", "exchange", "trading_class"]),
    ],
}


def analyze_dataset(
    data_dir: str,
    dataset: str,
    table_configs: List[Tuple[str, List[str]]],
    console: Console,
) -> Dict[str, any]:
    """
    Analyze all tables in a dataset for duplicates.

    Returns:
        Dictionary with analysis results per table
    """
    console.print(f"\n[cyan]Analyzing dataset: {dataset}[/cyan]")

    results = {}

    for table_name, primary_key in table_configs:
        table_path = Path(data_dir) / dataset / table_name

        if not table_path.exists():
            console.print(f"  [yellow]⚠[/yellow] {table_name}: Table does not exist (skipped)")
            results[table_name] = {"exists": False}
            continue

        try:
            console.print(f"  [dim]Analyzing {table_name}...[/dim]")

            report = get_duplicate_report(
                data_dir=data_dir,
                dataset=dataset,
                table_name=table_name,
                primary_key=primary_key,
            )

            results[table_name] = {
                "exists": True,
                "total_rows": report["total_rows"],
                "unique_rows": report["unique_rows"],
                "duplicate_rows": report["duplicate_rows"],
                "duplicate_pct": report["duplicate_pct"],
                "sample_duplicates": report["sample_duplicates"],
            }

            status = "✓" if report["duplicate_rows"] == 0 else "⚠"
            color = "green" if report["duplicate_rows"] == 0 else "yellow"
            console.print(
                f"  [{color}]{status}[/{color}] {table_name}: "
                f"{report['duplicate_rows']:,} duplicates ({report['duplicate_pct']:.2f}%)"
            )

        except Exception as e:
            console.print(f"  [red]✗[/red] {table_name}: Error - {str(e)}")
            results[table_name] = {
                "exists": True,
                "error": str(e),
            }

    return results


def create_summary_table(all_results: Dict[str, Dict[str, any]]) -> Table:
    """Create rich table with summary statistics."""
    table = Table(title="Duplicate Analysis Summary - All Datasets")

    table.add_column("Dataset", style="cyan")
    table.add_column("Table", style="cyan")
    table.add_column("Total Rows", justify="right")
    table.add_column("Unique Rows", justify="right")
    table.add_column("Duplicates", justify="right")
    table.add_column("% Duped", justify="right")
    table.add_column("Status", justify="center")

    grand_total_rows = 0
    grand_total_unique = 0
    grand_total_dupes = 0

    for dataset, tables in all_results.items():
        dataset_total_rows = 0
        dataset_total_unique = 0
        dataset_total_dupes = 0

        for table_name, result in tables.items():
            if not result.get("exists", False):
                table.add_row(
                    dataset,
                    table_name,
                    "-",
                    "-",
                    "-",
                    "-",
                    "[dim]N/A[/dim]",
                )
                continue

            if "error" in result:
                table.add_row(
                    dataset,
                    table_name,
                    "[red]ERROR[/red]",
                    "-",
                    "-",
                    "-",
                    "[red]✗[/red]",
                )
                continue

            total = result["total_rows"]
            unique = result["unique_rows"]
            dupes = result["duplicate_rows"]
            pct = result["duplicate_pct"]

            dataset_total_rows += total
            dataset_total_unique += unique
            dataset_total_dupes += dupes

            # Color code based on severity
            if pct == 0:
                status = "[green]✓[/green]"
                color = "green"
            elif pct < 10:
                status = "[yellow]⚠[/yellow]"
                color = "yellow"
            else:
                status = "[red]⚠⚠[/red]"
                color = "red"

            table.add_row(
                dataset,
                table_name,
                f"{total:,}",
                f"{unique:,}",
                f"[{color}]{dupes:,}[/{color}]",
                f"[{color}]{pct:.2f}%[/{color}]",
                status,
            )

        # Add dataset subtotal
        if dataset_total_rows > 0:
            dataset_pct = 100.0 * dataset_total_dupes / dataset_total_rows
            table.add_row(
                f"[bold]{dataset} TOTAL[/bold]",
                "",
                f"[bold]{dataset_total_rows:,}[/bold]",
                f"[bold]{dataset_total_unique:,}[/bold]",
                f"[bold]{dataset_total_dupes:,}[/bold]",
                f"[bold]{dataset_pct:.2f}%[/bold]",
                "",
            )
            table.add_section()

            grand_total_rows += dataset_total_rows
            grand_total_unique += dataset_total_unique
            grand_total_dupes += dataset_total_dupes

    # Add grand total
    if grand_total_rows > 0:
        grand_pct = 100.0 * grand_total_dupes / grand_total_rows
        table.add_row(
            "[bold cyan]GRAND TOTAL[/bold cyan]",
            "",
            f"[bold cyan]{grand_total_rows:,}[/bold cyan]",
            f"[bold cyan]{grand_total_unique:,}[/bold cyan]",
            f"[bold cyan]{grand_total_dupes:,}[/bold cyan]",
            f"[bold cyan]{grand_pct:.2f}%[/bold cyan]",
            "",
        )

    return table


def main():
    parser = argparse.ArgumentParser(
        description="Analyze all datasets for duplicate records"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./data_delta",
        help="Path to data directory (default: ./data_delta)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save report to file (optional)",
    )
    parser.add_argument(
        "--show-samples",
        action="store_true",
        help="Show sample duplicate rows for each table",
    )

    args = parser.parse_args()

    console = Console()

    # Header
    console.print("\n" + "=" * 80)
    console.print(Panel.fit(
        "[bold cyan]Duplicate Analysis Report[/bold cyan]\n"
        f"Data Directory: {args.data_dir}\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        border_style="cyan"
    ))
    console.print("=" * 80)

    # Analyze all datasets
    all_results = {}

    for dataset, table_configs in DATASET_CONFIGS.items():
        dataset_path = Path(args.data_dir) / dataset

        if not dataset_path.exists():
            console.print(f"\n[yellow]⚠ Dataset '{dataset}' does not exist (skipped)[/yellow]")
            continue

        results = analyze_dataset(
            data_dir=args.data_dir,
            dataset=dataset,
            table_configs=table_configs,
            console=console,
        )
        all_results[dataset] = results

    # Display summary table
    console.print("\n")
    summary_table = create_summary_table(all_results)
    console.print(summary_table)

    # Calculate recommendations
    console.print("\n" + "=" * 80)
    console.print("[bold]Recommendations:[/bold]\n")

    total_dupes = sum(
        result.get("duplicate_rows", 0)
        for tables in all_results.values()
        for result in tables.values()
        if result.get("exists", False) and "error" not in result
    )

    if total_dupes == 0:
        console.print("[green]✓ No duplicates found in any dataset![/green]")
        console.print("[green]  Your data is clean. No action needed.[/green]")
    else:
        console.print(f"[yellow]⚠ Found {total_dupes:,} duplicate rows across all datasets[/yellow]\n")
        console.print("[bold]Steps to clean up:[/bold]")
        console.print("1. [cyan]Backup your data[/cyan] (recommended):")
        console.print("   cp -r data_delta data_delta_backup_$(date +%Y%m%d)")
        console.print("")
        console.print("2. [cyan]Preview cleanup[/cyan] (dry-run):")

        for dataset in all_results.keys():
            dataset_dupes = sum(
                result.get("duplicate_rows", 0)
                for result in all_results[dataset].values()
                if result.get("exists", False) and "error" not in result
            )
            if dataset_dupes > 0:
                console.print(f"   dlt-ibapi deduplicate --dataset {dataset} --dry-run")

        console.print("")
        console.print("3. [cyan]Execute deduplication[/cyan]:")
        for dataset in all_results.keys():
            dataset_dupes = sum(
                result.get("duplicate_rows", 0)
                for result in all_results[dataset].values()
                if result.get("exists", False) and "error" not in result
            )
            if dataset_dupes > 0:
                console.print(f"   dlt-ibapi deduplicate --dataset {dataset}")

    console.print("=" * 80 + "\n")

    # Show sample duplicates if requested
    if args.show_samples:
        console.print("\n[bold]Sample Duplicate Rows:[/bold]\n")

        for dataset, tables in all_results.items():
            for table_name, result in tables.items():
                if not result.get("exists", False) or "error" in result:
                    continue

                if result["duplicate_rows"] > 0:
                    console.print(f"\n[cyan]{dataset}/{table_name}[/cyan]:")
                    sample_df = result["sample_duplicates"]

                    if not sample_df.empty:
                        # Show first 5 rows
                        console.print(sample_df.head(5).to_string())
                    else:
                        console.print("[dim]  (No sample data available)[/dim]")

    # Save to file if requested
    if args.output:
        with open(args.output, "w") as f:
            # Redirect console output to file
            file_console = Console(file=f, width=120)
            file_console.print(f"Duplicate Analysis Report")
            file_console.print(f"Data Directory: {args.data_dir}")
            file_console.print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file_console.print(summary_table)

        console.print(f"\n[green]✓ Report saved to: {args.output}[/green]")


if __name__ == "__main__":
    main()
