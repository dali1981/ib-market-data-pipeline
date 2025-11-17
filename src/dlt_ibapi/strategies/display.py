"""Rich display utilities for strategy selection commands.

Provides formatters for displaying IV rankings and selection results
in Rich tables with appropriate styling.
"""

from typing import List, Dict
from rich.table import Table
from rich.console import Console


def create_iv_rank_table(
    candidates: List[Dict],
    title: str = "IV Ratio Rankings",
) -> Table:
    """
    Create Rich table for IV ranking display.

    Args:
        candidates: List of candidate dicts with keys:
            - rank: Ranking number (1 = best)
            - symbol: Stock symbol
            - iv_ratio_entry: IV ratio at entry
            - iv_ratio_quartile: Q1-Q4 quartile
            - entry_cost_per_contract: Entry cost
            - spot_price: Underlying spot price
        title: Table title

    Returns:
        Formatted Rich Table

    Example:
        >>> table = create_iv_rank_table(candidates, "Top IV Ratios - 2025-11-13")
        >>> console.print(table)
    """
    table = Table(title=title, show_header=True, header_style="bold magenta")

    table.add_column("Rank", style="cyan", justify="right", width=6)
    table.add_column("Symbol", style="yellow", width=8)
    table.add_column("Earnings Time", style="dim", justify="center", width=14)
    table.add_column("Strike", style="white", justify="right", width=8)
    table.add_column("Short Expiry", style="dim", justify="center", width=12)
    table.add_column("Long Expiry", style="dim", justify="center", width=12)
    table.add_column("IV Ratio", style="green", justify="right", width=10)
    table.add_column("Quartile", style="magenta", justify="center", width=9)
    table.add_column("Entry Cost", style="blue", justify="right", width=12)
    table.add_column("Spot", style="dim", justify="right", width=8)

    for candidate in candidates:
        # Color code quartile
        quartile = candidate.get('iv_ratio_quartile', 'N/A')
        if quartile == 'Q4':
            quartile_style = "[bold green]Q4[/bold green]"
        elif quartile == 'Q3':
            quartile_style = "[yellow]Q3[/yellow]"
        elif quartile == 'Q2':
            quartile_style = "[dim]Q2[/dim]"
        else:
            quartile_style = "[dim]Q1[/dim]"

        # Format earnings time for display
        earnings_time = candidate.get('earnings_time', 'UNKNOWN')
        if earnings_time == 'PRE_MARKET':
            time_display = "[yellow]PRE[/yellow]"
        elif earnings_time == 'AFTER_HOURS':
            time_display = "[blue]AFTER[/blue]"
        else:
            time_display = "[dim]UNKNOWN[/dim]"

        # Format expiration dates
        short_expiry = candidate.get('short_expiry')
        long_expiry = candidate.get('long_expiry')
        short_expiry_str = str(short_expiry) if short_expiry else 'N/A'
        long_expiry_str = str(long_expiry) if long_expiry else 'N/A'

        table.add_row(
            str(candidate.get('rank', '')),
            candidate.get('symbol', ''),
            time_display,
            f"${candidate.get('strike', 0):.2f}",
            short_expiry_str,
            long_expiry_str,
            f"{candidate.get('iv_ratio_entry', 0):.3f}",
            quartile_style,
            f"${candidate.get('entry_cost_per_contract', 0):.2f}",
            f"${candidate.get('spot_price', 0):.2f}",
        )

    return table


def create_selection_stats_table(
    statistics: Dict,
    earnings_date: str,
    selection_criteria: Dict,
) -> Table:
    """
    Create Rich table for selection statistics summary.

    Args:
        statistics: Dict with keys:
            - count: Number of selected candidates
            - mean_iv_ratio: Average IV ratio
            - median_iv_ratio: Median IV ratio
            - mean_entry_cost: Average entry cost
            - expected_pnl: Expected P&L per contract
            - win_rate: Historical win rate percentage
        earnings_date: Earnings date string
        selection_criteria: Dict of applied filters

    Returns:
        Formatted Rich Table

    Example:
        >>> stats_table = create_selection_stats_table(stats, "2025-11-13", criteria)
        >>> console.print(stats_table)
    """
    table = Table(
        title=f"Selection Summary - {earnings_date}",
        show_header=False,
        box=None,
        padding=(0, 2),
    )

    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green bold")

    # Selection criteria
    if selection_criteria:
        table.add_row("", "")  # Spacer
        table.add_row("[bold]Applied Filters:[/bold]", "")
        for key, value in selection_criteria.items():
            if value is not None:
                formatted_key = key.replace('_', ' ').title()
                table.add_row(f"  {formatted_key}", str(value))

    # Statistics
    table.add_row("", "")  # Spacer
    table.add_row("[bold]Statistics:[/bold]", "")
    table.add_row("  Candidates Selected", str(statistics.get('count', 0)))
    table.add_row("  Mean IV Ratio", f"{statistics.get('mean_iv_ratio', 0):.3f}")
    table.add_row("  Median IV Ratio", f"{statistics.get('median_iv_ratio', 0):.3f}")

    if 'mean_entry_cost' in statistics:
        table.add_row("  Avg Entry Cost", f"${statistics['mean_entry_cost']:.2f}")

    if 'expected_pnl' in statistics:
        pnl = statistics['expected_pnl']
        pnl_style = "green" if pnl > 0 else "red"
        table.add_row("  Expected P&L", f"[{pnl_style}]${pnl:.2f}[/{pnl_style}]")

    if 'win_rate' in statistics:
        win_rate = statistics['win_rate']
        rate_style = "green" if win_rate >= 50 else "yellow" if win_rate >= 30 else "red"
        table.add_row("  Win Rate", f"[{rate_style}]{win_rate:.1f}%[/{rate_style}]")

    return table


def create_earnings_time_warning(earnings_time: str) -> str:
    """
    Create warning message about earnings time impact.

    Args:
        earnings_time: 'PRE_MARKET', 'AFTER_HOURS', or 'UNKNOWN'

    Returns:
        Formatted warning string

    Example:
        >>> warning = create_earnings_time_warning("PRE_MARKET")
        >>> console.print(warning)
    """
    if earnings_time == "PRE_MARKET":
        return (
            "[yellow]ℹ PRE_MARKET earnings:[/yellow] "
            "Entry = Previous day 3:00pm, Exit = Same day 4:00pm\n"
            "[dim]Spot price uses previous trading day's close[/dim]"
        )
    elif earnings_time == "AFTER_HOURS":
        return (
            "[yellow]ℹ AFTER_HOURS earnings:[/yellow] "
            "Entry = Earnings day 3:00pm, Exit = Next day 10:00am\n"
            "[dim]Spot price uses earnings day's close[/dim]"
        )
    else:
        return (
            "[yellow]ℹ UNKNOWN earnings time:[/yellow] "
            "Using AFTER_HOURS timing (conservative)\n"
            "[dim]Entry = Earnings day 3:00pm, Exit = Next day 10:00am[/dim]"
        )
