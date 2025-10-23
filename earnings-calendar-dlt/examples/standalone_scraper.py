"""Example: Using the scraper standalone without dlt or Dagster."""

from earnings_calendar import fetch_earnings_calendar
from rich.console import Console
from rich.table import Table

console = Console()


def main():
    """Fetch and display upcoming earnings."""
    console.print("[bold blue]Fetching earnings calendar...[/bold blue]")

    # Fetch next 7 days
    earnings = fetch_earnings_calendar(days_ahead=7)

    # Create table
    table = Table(title="Upcoming Earnings (Next 7 Days)")
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Company", style="white")
    table.add_column("Date", style="green")
    table.add_column("Time", style="yellow")
    table.add_column("EPS Est.", style="magenta", justify="right")

    for record in earnings[:20]:  # Show first 20
        table.add_row(
            record["symbol"],
            record["company_name"][:30],  # Truncate long names
            record["earnings_date"],
            record["earnings_time"] or "TBD",
            f"{record['eps_forecast']:.2f}" if record["eps_forecast"] else "N/A",
        )

    console.print(table)
    console.print(f"\n[bold]Total records: {len(earnings)}[/bold]")


if __name__ == "__main__":
    main()
