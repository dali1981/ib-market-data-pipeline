"""Example: Querying earnings data using the read API."""

from earnings_calendar import EarningsCalendarReader
from rich.console import Console
from rich.table import Table
from datetime import datetime, timedelta

console = Console()


def main():
    """Query and display earnings data."""
    reader = EarningsCalendarReader(
        data_path="./data/nasdaq_earnings/earnings_calendar"
    )

    console.print("[bold blue]Earnings Calendar Query Examples[/bold blue]\n")

    # 1. Get upcoming earnings
    console.print("[bold]1. Upcoming Earnings (Next 7 Days):[/bold]")
    upcoming = reader.get_upcoming_earnings(days_ahead=7)

    table = Table()
    table.add_column("Symbol", style="cyan")
    table.add_column("Date", style="green")
    table.add_column("Time", style="yellow")
    table.add_column("EPS Est.", justify="right")

    for record in upcoming[:10]:
        table.add_row(
            record["symbol"],
            record["earnings_date"],
            record.get("earnings_time", "TBD"),
            f"{record['eps_forecast']:.2f}" if record.get("eps_forecast") else "N/A",
        )

    console.print(table)
    console.print(f"Total upcoming: {len(upcoming)}\n")

    # 2. Get earnings for specific ticker
    console.print("[bold]2. Earnings History for AAPL:[/bold]")
    aapl_earnings = reader.get_earnings_by_ticker("AAPL", limit=5)

    for record in aapl_earnings:
        console.print(
            f"  {record['earnings_date']}: "
            f"Est: {record.get('eps_forecast', 'N/A')}, "
            f"Actual: {record.get('eps_actual', 'N/A')}"
        )
    console.print()

    # 3. Get earnings on specific date
    today = datetime.now().date()
    console.print(f"[bold]3. Earnings on {today}:[/bold]")
    today_earnings = reader.get_earnings_by_date(today.isoformat())
    console.print(f"  {len(today_earnings)} companies reporting\n")

    # 4. Get earnings with surprises
    console.print("[bold]4. Recent Earnings Surprises (>5%):[/bold]")
    surprises = reader.get_earnings_with_surprises(
        min_surprise_pct=5.0,
        limit=10
    )

    for record in surprises:
        surprise_pct = record.get("eps_surprise_pct", 0)
        color = "green" if surprise_pct > 0 else "red"
        console.print(
            f"  [{color}]{record['symbol']}[/{color}]: "
            f"{surprise_pct:+.2f}% surprise on {record['earnings_date']}"
        )
    console.print()

    # 5. Get statistics
    console.print("[bold]5. Dataset Statistics:[/bold]")
    stats = reader.get_earnings_stats()
    console.print(f"  Total records: {stats.get('total_records', 0)}")
    console.print(f"  Unique symbols: {stats.get('unique_symbols', 0)}")
    console.print(f"  Date range: {stats.get('earliest_date')} to {stats.get('latest_date')}")
    console.print(f"  Reported earnings: {stats.get('reported_count', 0)}")
    if stats.get("avg_surprise_pct"):
        console.print(f"  Avg surprise: {stats['avg_surprise_pct']:.2f}%")


if __name__ == "__main__":
    main()
