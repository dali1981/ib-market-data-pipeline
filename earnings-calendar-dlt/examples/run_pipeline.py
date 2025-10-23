"""Example: Running the dlt pipeline to store data in Parquet."""

from earnings_calendar import run_pipeline
from earnings_calendar.config import get_default_config
from rich.console import Console

console = Console()


def main():
    """Run the earnings calendar pipeline."""
    console.print("[bold blue]Running earnings calendar pipeline...[/bold blue]")

    config = get_default_config()
    console.print(f"Days ahead: {config.scraper.days_ahead}")
    console.print(f"Destination: {config.dlt.destination}")
    console.print(f"Dataset: {config.dlt.dataset_name}\n")

    # Run pipeline
    load_info = run_pipeline(
        days_ahead=30,
        destination="filesystem",
        dataset_name="nasdaq_earnings",
    )

    # Display results
    console.print(f"[bold green]Pipeline completed![/bold green]")
    console.print(f"Load ID: {load_info.load_packages[0].load_id}")

    # Show package info
    for package in load_info.load_packages:
        console.print(f"\nPackage: {package.package_path}")
        console.print(f"State: {package.state}")

        # Count records
        total_records = package.state.get("finished_count", 0)
        console.print(f"Records loaded: {total_records}")


if __name__ == "__main__":
    main()
