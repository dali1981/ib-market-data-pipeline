"""
CLI interface for dlt-ibapi using Typer.

Provides commands for:
- Initializing config files
- Testing IB connection
- Fetching data manually
- Viewing current configuration
"""

from pathlib import Path
from typing import Optional, List
import json

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .config_loader import (
    load_config,
    create_user_config_template,
    get_connection_config,
    get_user_config_path,
    get_package_config_path,
)
from .sources import ib_historical_bars, ib_contract_details
from datetime import date, datetime, timedelta
import dlt

# Import structlog configuration and logging utilities
from .utils.structlog_config import configure_structlog
from .utils.logging import get_logger

app = typer.Typer(
    name="dlt-ibapi",
    help="CLI for Interactive Brokers DLT connector",
    add_completion=False,
)
console = Console()

# Create snapshot subcommand group
snapshot_app = typer.Typer(help="Option chain snapshot commands")
app.add_typer(snapshot_app, name="snapshot")

# Create equity subcommand group
equity_app = typer.Typer(help="Equity bars commands")
app.add_typer(equity_app, name="equity")


@app.callback()
def global_options(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable DEBUG level logging",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Only show WARNING and ERROR logs",
    ),
    json_logs: bool = typer.Option(
        False,
        "--json-logs",
        help="Output logs in JSON format",
    ),
    log_file: Optional[str] = typer.Option(
        None,
        "--log-file",
        help="Write logs to file with rotation (10MB max, 5 backups)",
    ),
):
    """
    Global options for all CLI commands.

    These options control logging behavior across all commands.
    """
    # Configure structlog with the provided options
    configure_structlog(
        verbose=verbose,
        quiet=quiet,
        json_logs=json_logs,
        log_file=log_file,
    )


@app.command()
def init(
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        "-d",
        help="Directory to create config in (default: current directory)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing config file",
    ),
):
    """
    Initialize dlt-ibapi configuration in your project.

    Creates .dlt-ibapi/ib_gateway.yaml with default settings.
    """
    target_dir = directory or Path.cwd()
    config_file = target_dir / ".dlt-ibapi" / "ib_gateway.yaml"

    if config_file.exists() and not force:
        console.print(
            f"[yellow]Config file already exists:[/yellow] {config_file}",
            style="bold",
        )
        console.print("Use --force to overwrite")
        raise typer.Exit(1)

    created_file = create_user_config_template(target_dir)
    console.print(f"[green]✓[/green] Created config file: {created_file}")
    console.print("\n[cyan]Next steps:[/cyan]")
    console.print("1. Edit the config file to customize your settings")
    console.print("2. Test connection with: dlt-ibapi test-connection")


@app.command()
def show_config(
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file (default: auto-detect)",
    ),
):
    """
    Display current configuration with source information.

    Shows which settings come from default, user config, or env vars.
    """
    # Show where configs are being loaded from
    console.print("\n[bold cyan]Configuration Sources:[/bold cyan]")

    default_path = get_package_config_path()
    console.print(f"  Default: {default_path}")

    user_path = config_file or get_user_config_path()
    if user_path and user_path.exists():
        console.print(f"  User:    {user_path} [green]✓[/green]")
    else:
        console.print(f"  User:    [dim]Not found[/dim]")

    console.print(f"  Env:     [dim]IB_HOST, IB_PORT, etc.[/dim]")

    # Load and display merged config
    config = load_config(config_file)

    console.print("\n[bold cyan]Merged Configuration:[/bold cyan]")

    # Connection settings
    table = Table(title="Connection Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Host", str(config.connection.host))
    table.add_row("Port", str(config.connection.port))
    table.add_row("Client ID", str(config.connection.client_id))
    table.add_row("Ready Timeout", f"{config.connection.ready_timeout}s")

    console.print(table)

    # Historical settings
    table = Table(title="Historical Data Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Duration", config.historical.duration)
    table.add_row("Bar Size", config.historical.bar_size)
    table.add_row("What to Show", config.historical.what_to_show)
    table.add_row("Use RTH", str(config.historical.use_rth))
    table.add_row("Timeout", f"{config.historical.timeout}s")

    console.print(table)


@app.command()
def test_connection(
    host: Optional[str] = typer.Option(None, "--host", help="IB Gateway/TWS host"),
    port: Optional[int] = typer.Option(None, "--port", help="IB Gateway/TWS port"),
    client_id: Optional[int] = typer.Option(None, "--client-id", help="Client ID"),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
):
    """
    Test connection to IB Gateway/TWS.

    Attempts to connect and fetch contract details for AAPL to verify setup.
    """
    from ib_connector import IBRuntime

    console.print("\n[bold cyan]Testing IB Gateway/TWS Connection...[/bold cyan]\n")

    # Get config
    conn_config = get_connection_config(config_file)

    # Override with CLI args if provided
    if host:
        conn_config.host = host
    if port:
        conn_config.port = port
    if client_id:
        conn_config.client_id = client_id

    console.print(f"Host:      {conn_config.host}")
    console.print(f"Port:      {conn_config.port}")
    console.print(f"Client ID: {conn_config.client_id}")
    console.print()

    try:
        # Try to connect
        with console.status("[bold green]Connecting..."):
            runtime = IBRuntime(
                host=conn_config.host,
                port=conn_config.port,
                client_id=conn_config.client_id,
            )
            runtime.start(ready_timeout=conn_config.ready_timeout)

        console.print("[green]✓[/green] Connected successfully!")

        # Try to fetch a simple contract
        with console.status("[bold green]Fetching AAPL contract details..."):
            from ib_connector import ContractDetailsService, make_stock

            svc = ContractDetailsService(runtime)
            contract = make_stock("AAPL", exch="SMART", curr="USD")
            details = svc.fetch(contract, timeout=10.0)

        if details:
            detail = details[0]
            console.print(f"[green]✓[/green] Received contract details for {detail.contract.symbol}")
            console.print(f"  Contract ID: {detail.contract.conId}")
            console.print(f"  Exchange: {detail.contract.exchange}")
            console.print(f"  Company: {detail.longName}")

        runtime.stop()
        console.print("\n[green bold]✓ Connection test successful![/green bold]")

    except Exception as e:
        console.print(f"\n[red bold]✗ Connection failed:[/red bold] {str(e)}")
        console.print("\n[yellow]Troubleshooting tips:[/yellow]")
        console.print("1. Ensure IB Gateway or TWS is running")
        console.print("2. Check that API connections are enabled in IB settings")
        console.print("3. Verify the port number matches your IB Gateway/TWS configuration")
        console.print("4. Ensure client_id is not already in use")
        raise typer.Exit(1)


@app.command()
def fetch(
    symbols: List[str] = typer.Argument(..., help="Stock symbols to fetch"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file (JSON or CSV)"
    ),
    data_type: str = typer.Option(
        "historical", "--type", "-t", help="Data type: historical or contract"
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
):
    """
    Fetch data for symbols and optionally save to file.

    Examples:
        dlt-ibapi fetch AAPL GOOGL MSFT
        dlt-ibapi fetch AAPL --type contract -o contracts.json
        dlt-ibapi fetch TSLA --type historical -o tsla_bars.json
    """
    from ib_connector import IBRuntime

    console.print(f"\n[bold cyan]Fetching {data_type} data for: {', '.join(symbols)}[/bold cyan]\n")

    # Get config
    conn_config = get_connection_config(config_file)

    try:
        # Connect
        with console.status("[bold green]Connecting to IB Gateway..."):
            runtime = IBRuntime(
                host=conn_config.host,
                port=conn_config.port,
                client_id=conn_config.client_id,
            )
            runtime.start(ready_timeout=conn_config.ready_timeout)

        console.print("[green]✓[/green] Connected")

        all_data = []

        for symbol in symbols:
            with console.status(f"[bold green]Fetching {symbol}..."):
                if data_type == "historical":
                    data_iter = ib_historical_bars(
                        symbol=symbol,
                        connection_config=conn_config,
                    )
                elif data_type == "contract":
                    data_iter = ib_contract_details(
                        symbols=[symbol],
                        connection_config=conn_config,
                    )
                else:
                    console.print(f"[red]Unknown data type: {data_type}[/red]")
                    raise typer.Exit(1)

                symbol_data = list(data_iter)
                all_data.extend(symbol_data)
                console.print(f"[green]✓[/green] {symbol}: {len(symbol_data)} records")

        runtime.stop()

        # Output
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("w") as f:
                json.dump(all_data, f, indent=2, default=str)
            console.print(f"\n[green]✓[/green] Saved to: {output}")
        else:
            # Print sample
            console.print(f"\n[cyan]Total records:[/cyan] {len(all_data)}")
            if all_data:
                console.print("\n[cyan]Sample record:[/cyan]")
                rprint(all_data[0])

    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@snapshot_app.command(name="capture")
def snapshot_capture(
    symbol: Optional[str] = typer.Argument(None, help="Underlying symbol (e.g., AAPL) - use this OR --earnings-date"),
    snapshot_date: Optional[str] = typer.Option(
        None, "--date", "-d", help="Snapshot date (YYYY-MM-DD, default: today)"
    ),
    earnings_date: Optional[str] = typer.Option(
        None, "--earnings-date", help="Capture snapshots for all symbols with earnings on this date (YYYY-MM-DD)"
    ),
    earnings_time: Optional[str] = typer.Option(
        None, "--earnings-time", help="Filter by earnings time (PRE_MARKET, AFTER_HOURS, UNKNOWN) - only with --earnings-date"
    ),
    min_dte: int = typer.Option(7, "--min-dte", help="Minimum days to expiration"),
    max_dte: int = typer.Option(365, "--max-dte", help="Maximum days to expiration"),
    pipeline_name: str = typer.Option(
        "ib_snapshots", "--pipeline-name", "--pipeline", help="Pipeline name"
    ),
    dataset: str = typer.Option("option_chains", "--dataset", help="Dataset name"),
    earnings_dataset: str = typer.Option("earnings", "--earnings-dataset", help="Earnings dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --pipeline-name instead"),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file", help="Write logs to file (auto-rotates at 10MB)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress INFO logs"),
    use_delta: bool = typer.Option(False, "--delta", help="Use Delta Lake format (ACID transactions, time travel)"),
):
    """
    Capture option chain snapshot for a symbol or batch snapshot for earnings date.

    Single symbol mode:
        dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

    Batch earnings mode:
        dlt-ibapi snapshot --earnings-date 2025-11-13 --min-dte 0 --max-dte 7
        dlt-ibapi snapshot --earnings-date 2025-11-13 --earnings-time PRE_MARKET
    """
    from .cli.snapshot import execute_snapshot, execute_batch_snapshot_for_earnings
    from .cli.models import SnapshotParams
    from .repositories import OptionChainSnapshotReader

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --pipeline-name instead.[/yellow]")
        pipeline_name = database.replace(".duckdb", "")

    # Validate: Need either symbol OR earnings_date (not both, not neither)
    if symbol and earnings_date:
        console.print("[red]Error: Cannot specify both symbol and --earnings-date. Use one or the other.[/red]")
        raise typer.Exit(1)

    if not symbol and not earnings_date:
        console.print("[red]Error: Must specify either symbol or --earnings-date[/red]")
        raise typer.Exit(1)

    if earnings_time and not earnings_date:
        console.print("[red]Error: --earnings-time can only be used with --earnings-date[/red]")
        raise typer.Exit(1)

    # Parse dates
    snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date() if snapshot_date else date.today()
    earn_date = datetime.strptime(earnings_date, "%Y-%m-%d").date() if earnings_date else None

    # Get connection config
    conn_config = get_connection_config(config_file)

    # Branch: Single symbol or batch earnings mode
    if symbol:
        # ========== SINGLE SYMBOL MODE ==========
        console.print(f"\n[bold cyan]Capturing option chain snapshot for {symbol}[/bold cyan]\n")

        console.print(f"Symbol:        {symbol}")
        console.print(f"Date:          {snap_date}")
        console.print(f"DTE range:     {min_dte} to {max_dte}")
        console.print(f"Pipeline:      {pipeline_name}")
        console.print(f"Dataset:       {dataset}\n")

        try:
            # Create params
            params = SnapshotParams(
                underlying=symbol,
                snapshot_date=snap_date,
                min_dte=min_dte,
                max_dte=max_dte,
                pipeline_name=pipeline_name,
                dataset_name=dataset,
                use_delta=use_delta,
            )

            # Execute snapshot
            with console.status("[bold green]Capturing snapshot..."):
                result = execute_snapshot(params, connection_config=conn_config)

            if not result.success:
                console.print(f"[red]✗[/red] Snapshot failed: {result.error}")
                raise typer.Exit(1)

            console.print("[green]✓[/green] Snapshot captured successfully!")

            # Display warnings if any
            if result.warnings:
                for warning in result.warnings:
                    console.print(f"[yellow]Warning:[/yellow] {warning}")

            # Query and display results
            from .cli.models import _get_default_database_path
            data_path = _get_default_database_path()
            reader = OptionChainSnapshotReader(str(data_path), dataset)
            chain = reader.get_chain_for_date(symbol, snap_date, min_dte, max_dte)

            if not chain.empty:
                total_exp = sum(chain['expiration_count'])
                total_strikes = sum(chain['strike_count'])

                table = Table(title=f"Option Chain Snapshot: {symbol} ({snap_date})")
                table.add_column("Exchange", style="cyan")
                table.add_column("Trading Class", style="cyan")
                table.add_column("Expirations", justify="right")
                table.add_column("Strikes", justify="right")

                for _, row in chain.iterrows():
                    table.add_row(
                        row['exchange'],
                        row['trading_class'],
                        str(row['expiration_count']),
                        str(row['strike_count'])
                    )

                console.print(table)
                console.print(f"\n[green]Total:[/green] {total_exp} expirations, {total_strikes} strikes")

        except Exception as e:
            console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
            raise typer.Exit(1)

    else:
        # ========== BATCH EARNINGS MODE ==========
        console.print(f"\n[bold cyan]Capturing Option Chain Snapshots for Earnings Date: {earn_date}[/bold cyan]\n")

        console.print(f"Earnings Date: {earn_date}")
        console.print(f"Snapshot Date: {snap_date}")
        if earnings_time:
            console.print(f"Time Filter:   {earnings_time}")
        console.print(f"DTE range:     {min_dte} to {max_dte}")
        console.print(f"Pipeline:      {pipeline_name}")
        console.print(f"Dataset:       {dataset}\n")

        try:
            # Create params
            params = SnapshotParams(
                earnings_date=earn_date,
                earnings_time_filter=earnings_time,
                snapshot_date=snap_date,
                min_dte=min_dte,
                max_dte=max_dte,
                pipeline_name=pipeline_name,
                dataset_name=dataset,
                earnings_dataset_name=earnings_dataset,
                use_delta=use_delta,
            )

            # Define progress callback for live updates
            def progress_callback(symbol: str, current: int, total: int):
                console.print(f"  [{current}/{total}] Processing {symbol}...")

            # Execute batch snapshot with live progress
            console.print(f"\n[bold green]Processing {params.earnings_time_filter or 'all'} earnings snapshots...[/bold green]\n")
            result = execute_batch_snapshot_for_earnings(
                params,
                connection_config=conn_config,
                progress_callback=progress_callback
            )

            # Display results
            if result.total_symbols == 0:
                console.print("[yellow]No symbols found with earnings on the specified date[/yellow]")
                if result.warnings:
                    for warning in result.warnings:
                        console.print(f"[yellow]Warning:[/yellow] {warning}")
                return

            # Create summary table
            table = Table(title=f"Batch Snapshot Results: {earn_date}")
            table.add_column("Symbol", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Expirations", justify="right")
            table.add_column("Strikes", justify="right")
            table.add_column("Duration", justify="right")

            for res in result.individual_results:
                status = "✓" if res.success else "✗"
                status_style = "green" if res.success else "red"
                table.add_row(
                    res.underlying,
                    f"[{status_style}]{status}[/{status_style}]",
                    str(res.expirations_count) if res.success else "-",
                    str(res.strikes_count) if res.success else "-",
                    f"{res.duration_seconds:.1f}s",
                )

            console.print(table)

            # Summary statistics
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Total symbols:      {result.total_symbols}")
            console.print(f"  Successful:         [green]{result.successful_snapshots}[/green]")
            if result.failed_snapshots > 0:
                console.print(f"  Failed:             [red]{result.failed_snapshots}[/red] ({', '.join(result.failed_symbols)})")
            console.print(f"  Total duration:     {result.duration_seconds:.1f}s")

            # Display warnings
            if result.warnings:
                console.print("\n[yellow]Warnings:[/yellow]")
                for warning in result.warnings[:10]:  # Limit to first 10 warnings
                    console.print(f"  • {warning}")
                if len(result.warnings) > 10:
                    console.print(f"  ... and {len(result.warnings) - 10} more warnings")

            # Exit with error if all failed
            if result.failed_snapshots == result.total_symbols:
                console.print("\n[red]✗[/red] All snapshots failed!")
                raise typer.Exit(1)
            elif result.failed_snapshots > 0:
                console.print("\n[yellow]⚠[/yellow] Some snapshots failed")
            else:
                console.print("\n[green]✓[/green] All snapshots completed successfully!")

        except Exception as e:
            console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
            raise typer.Exit(1)


@snapshot_app.command(name="list")
def snapshot_list(
    snapshot_date: Optional[str] = typer.Option(None, "--date", help="Filter by snapshot date (YYYY-MM-DD)"),
    earnings_date: Optional[str] = typer.Option(None, "--earnings-date", help="Filter symbols with earnings on this date"),
    symbols: Optional[List[str]] = typer.Option(None, "--symbols", "-s", help="Filter by symbols (comma-separated or repeat flag)"),
    dataset: str = typer.Option("option_chains", "--dataset", help="Dataset name"),
):
    """
    List symbols with option chain snapshots.

    Example:
        dlt-ibapi snapshot list --date 2025-11-17
        dlt-ibapi snapshot list --earnings-date 2025-11-17
        dlt-ibapi snapshot list --symbols "AAPL,MSFT"
        dlt-ibapi snapshot list --symbols AAPL --symbols MSFT
    """
    from .repositories import OptionChainSnapshotReader, EarningsCalendarReader
    from .cli.models import _get_default_database_path
    from rich.table import Table

    logger = get_logger(__name__)
    data_path = _get_default_database_path()

    try:
        # Parse date if provided
        snap_date = None
        if snapshot_date:
            snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()

        earn_date = None
        if earnings_date:
            earn_date = datetime.strptime(earnings_date, "%Y-%m-%d").date()

        # If earnings-date provided, get symbols from earnings
        earnings_symbols = None
        if earn_date:
            earnings_reader = EarningsCalendarReader(str(data_path), "earnings")
            earnings_df = earnings_reader.get_earnings_on_date(earn_date)
            if not earnings_df.empty:
                earnings_symbols = earnings_df["symbol"].unique().tolist()
                logger.info(f"Found {len(earnings_symbols)} symbols with earnings on {earn_date}")
            else:
                console.print(f"[yellow]No earnings found on {earn_date}[/yellow]")
                return

        # Get snapshots
        reader = OptionChainSnapshotReader(str(data_path), dataset)

        # Determine which symbols to query
        query_symbols = None
        if symbols:
            # Handle both comma-separated and multiple flag usage
            query_symbols = []
            for s in symbols:
                if ',' in s:
                    # Split comma-separated values
                    query_symbols.extend([x.strip().upper() for x in s.split(',')])
                else:
                    query_symbols.append(s.upper())
        elif earnings_symbols:
            query_symbols = earnings_symbols

        snapshots = reader.get_symbols_with_snapshots(
            snapshot_date=snap_date,
            symbols=query_symbols,
        )

        if snapshots.empty:
            console.print("[dim]No option chain snapshots found[/dim]")
            return

        # Display as table
        title_parts = ["Option Chain Snapshots"]
        if snap_date:
            title_parts.append(f"on {snap_date}")
        if earn_date:
            title_parts.append(f"(Earnings: {earn_date})")

        table = Table(title=" ".join(title_parts))
        table.add_column("Symbol", style="cyan")
        table.add_column("Snapshot Date", style="green")
        table.add_column("Expirations", justify="right")
        table.add_column("Strikes", justify="right")

        for _, row in snapshots.iterrows():
            table.add_row(
                row["symbol"],
                str(row["snapshot_date"]),
                str(row["expiration_count"]),
                str(row["strike_count"]),
            )

        console.print(table)

        # Summary
        total_snapshots = len(snapshots)
        if earnings_symbols:
            console.print(f"\n[dim]Total: {total_snapshots} snapshots (out of {len(earnings_symbols)} earnings symbols)[/dim]")
        else:
            console.print(f"\n[dim]Total: {total_snapshots} snapshot(s)[/dim]")

    except Exception as e:
        logger.error(f"list_snapshots.error: {e}", exc_info=True)
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@equity_app.command(name="list")
def equity_list(
    earnings_date: Optional[str] = typer.Option(
        None, "--earnings-date", help="Filter symbols with earnings on this date (YYYY-MM-DD)"
    ),
    symbols: Optional[List[str]] = typer.Option(
        None, "--symbols", "-s", help="Filter specific symbols (comma-separated or repeat flag)"
    ),
    bar_size: str = typer.Option(
        "1 day", "--bar-size", help="Filter by bar size"
    ),
    dataset: str = typer.Option("stocks", "--dataset", help="Dataset name"),
):
    """
    List equity bars summary with bar counts and date ranges.

    Displays a table showing all equity symbols with their bar counts,
    first bar date, and last bar date. Can filter by earnings date or
    specific symbols.

    Examples:
        # List all equity bars
        dlt-ibapi equity list

        # List equity bars for symbols with earnings on specific date
        dlt-ibapi equity list --earnings-date 2025-11-17

        # List equity bars for specific symbols
        dlt-ibapi equity list --symbols AAPL,MSFT,GOOGL

        # List equity bars for different bar size
        dlt-ibapi equity list --bar-size "1 hour"

        # Combine filters
        dlt-ibapi equity list --earnings-date 2025-11-17 --bar-size "1 day"
    """
    from .repositories import EquityBarsReader, EarningsCalendarReader
    from .cli.models import _get_default_database_path

    logger = get_logger(__name__)
    data_path = _get_default_database_path()

    try:
        # Parse earnings date if provided
        earn_date = None
        if earnings_date:
            earn_date = datetime.strptime(earnings_date, "%Y-%m-%d").date()

        # If earnings-date provided, get symbols from earnings
        earnings_symbols = None
        if earn_date:
            earnings_reader = EarningsCalendarReader(str(data_path), "earnings")
            earnings_df = earnings_reader.get_earnings_on_date(earn_date)
            if not earnings_df.empty:
                earnings_symbols = earnings_df["symbol"].unique().tolist()
                logger.info(f"Found {len(earnings_symbols)} symbols with earnings on {earn_date}")
            else:
                console.print(f"[yellow]No earnings found on {earn_date}[/yellow]")
                return

        # Parse symbols parameter (handle both comma-separated and multiple flags)
        query_symbols = None
        if symbols:
            query_symbols = []
            for s in symbols:
                if ',' in s:
                    # Split comma-separated values
                    query_symbols.extend([x.strip().upper() for x in s.split(',')])
                else:
                    query_symbols.append(s.upper())
        elif earnings_symbols:
            query_symbols = earnings_symbols

        # Get equity bars summary
        reader = EquityBarsReader(str(data_path), dataset)
        summary = reader.get_symbols_summary(bar_size=bar_size, symbols=query_symbols)

        if summary.empty:
            console.print("[dim]No equity bars found[/dim]")
            return

        # Display as table
        title_parts = ["Backfill Summary"]
        if earn_date:
            title_parts.append(f"(Earnings: {earn_date})")
        if bar_size:
            title_parts.append(f"[{bar_size}]")

        table = Table(title=" ".join(title_parts))
        table.add_column("Symbol", style="cyan")
        table.add_column("Bar Count", justify="right")
        table.add_column("First Bar", style="dim")
        table.add_column("Last Bar", style="dim")

        for _, row in summary.iterrows():
            table.add_row(
                row['symbol'],
                str(int(row['bar_count'])),
                str(row['first_bar'].date()),
                str(row['last_bar'].date())
            )

        console.print()
        console.print(table)
        console.print()
        console.print(f"[dim]Total: {len(summary)} symbol(s)[/dim]")

    except ValueError as e:
        console.print(f"[red]Invalid date format: {e}[/red]")
        logger.error(f"equity_list.invalid_date: {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.error(f"equity_list.error: {e}", exc_info=True)
        raise typer.Exit(1)


@app.command()
def backfill_options(
    symbol: Optional[str] = typer.Argument(None, help="Underlying symbol (e.g., AAPL) or use --earnings-date"),
    spot_price: Optional[float] = typer.Argument(None, help="Current spot price (or auto-extract with --earnings-date)"),
    earnings_date: Optional[str] = typer.Option(
        None, "--earnings-date", help="Earnings date to backfill all symbols (YYYY-MM-DD, mutually exclusive with symbol)"
    ),
    symbols: Optional[str] = typer.Option(
        None, "--symbols", help="Filter specific symbols when using --earnings-date (comma-separated: AAPL,MSFT)"
    ),
    k_expirations: Optional[int] = typer.Option(
        None, "--k-expirations", help="Limit to k closest expirations (soonest to expire)"
    ),
    snapshot_date: Optional[str] = typer.Option(
        None, "--snapshot-date", help="Snapshot date to read expirations from (defaults to earnings-date)"
    ),
    start: Optional[str] = typer.Option(
        None, "--start", help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="End date (YYYY-MM-DD, default: today)"
    ),
    bar_size: str = typer.Option("1 day", "--bar-size", "-b", help="Bar size"),
    mode: str = typer.Option("atm", "--mode", "-m", help="Selection mode: atm, moneyness, delta, all"),
    k_strikes: int = typer.Option(5, "--k-strikes", "-k", help="K strikes for ATM mode"),
    min_dte: int = typer.Option(7, "--min-dte", help="Minimum days to expiration (not used in earnings mode)"),
    max_dte: int = typer.Option(60, "--max-dte", help="Maximum days to expiration (not used in earnings mode)"),
    pipeline_name: str = typer.Option("ib_options", "--pipeline-name", "--pipeline", help="Pipeline name"),
    dataset: str = typer.Option("options", "--dataset", help="Dataset name"),
    earnings_dataset: str = typer.Option("earnings", "--earnings-dataset", help="Earnings dataset name"),
    option_chains_dataset: str = typer.Option("option_chains", "--option-chains-dataset", help="Option chains dataset name"),
    stocks_dataset: str = typer.Option("stocks", "--stocks-dataset", help="Stocks dataset name (for spot price extraction)"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --pipeline-name instead"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
    # New options
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress INFO logs"),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="Write logs to file with rotation"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Output structured JSON logs"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without doing it"),
    client_id: Optional[int] = typer.Option(None, "--client-id", help="IB Gateway client ID (overrides config default)"),
    use_delta: bool = typer.Option(False, "--delta", help="Use Delta Lake format (ACID transactions, time travel)"),
):
    """
    Backfill option bars with gap detection.

    Two modes:
    1. Single symbol: dlt-ibapi backfill-options AAPL 150.0 --mode atm
    2. Earnings batch: dlt-ibapi backfill-options --earnings-date 2025-11-13 (auto spot prices, all expirations)

    Examples:
        dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
        dlt-ibapi backfill-options --earnings-date 2025-11-13 --start 2025-01-01 --end 2025-11-13 --k-expirations 6
        dlt-ibapi backfill-options --earnings-date 2025-11-13 --symbols AAPL,MSFT,GOOGL --k-expirations 6
        dlt-ibapi backfill-options AAPL 150.0 --pipeline-name my_options --verbose
    """
    from .cli import BackfillOptionsParams, execute_backfill_options
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

    # Validate mutual exclusivity
    if symbol and earnings_date:
        console.print("[red]Error: Cannot specify both symbol and --earnings-date. Use one or the other.[/red]")
        raise typer.Exit(1)
    if not symbol and not earnings_date:
        console.print("[red]Error: Must specify either symbol or --earnings-date.[/red]")
        raise typer.Exit(1)

    # Validate single symbol mode requirements
    if symbol and spot_price is None:
        console.print("[red]Error: spot_price is required when using symbol (single mode).[/red]")
        raise typer.Exit(1)

    # Validate earnings mode restrictions
    if earnings_date and spot_price is not None:
        console.print("[red]Error: spot_price should not be specified with --earnings-date (auto-extracted).[/red]")
        raise typer.Exit(1)

    # Validate --symbols only with --earnings-date
    if symbols and not earnings_date:
        console.print("[red]Error: --symbols can only be used with --earnings-date.[/red]")
        raise typer.Exit(1)

    # Parse symbols list
    symbols_list = None
    if symbols:
        symbols_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not symbols_list:
            console.print("[red]Error: --symbols list is empty.[/red]")
            raise typer.Exit(1)

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --pipeline-name instead.[/yellow]")
        pipeline_name = database.replace(".duckdb", "")

    # Parse dates
    start_date = datetime.strptime(start, "%Y-%m-%d").date() if start else date.today() - timedelta(days=30)
    end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()
    earnings_date_parsed = datetime.strptime(earnings_date, "%Y-%m-%d").date() if earnings_date else None
    snapshot_date_parsed = datetime.strptime(snapshot_date, "%Y-%m-%d").date() if snapshot_date else None

    # Validate selection mode
    valid_modes = ["atm", "moneyness", "delta", "all"]
    if mode not in valid_modes:
        console.print(f"[red]✗ Invalid mode: {mode}. Choose from: {', '.join(valid_modes)}[/red]")
        raise typer.Exit(1)

    # Display plan
    mode_desc = f"earnings on {earnings_date_parsed}" if earnings_date_parsed else symbol
    console.print(f"\n[bold cyan]{'DRY RUN: ' if dry_run else ''}Backfilling option bars for {mode_desc}[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    if earnings_date_parsed:
        table.add_row("Mode", "Earnings Batch")
        table.add_row("Earnings Date", str(earnings_date_parsed))
        table.add_row("Spot Prices", "Auto-extracted from equity bars")
        table.add_row("Expirations", f"All beyond earnings{f' (limit: {k_expirations})' if k_expirations else ''}")
    else:
        table.add_row("Mode", "Single Symbol")
        table.add_row("Underlying", f"{symbol} @ ${spot_price}")
        table.add_row("DTE Range", f"{min_dte} to {max_dte}")
    table.add_row("Date Range", f"{start_date} to {end_date}")
    table.add_row("Bar Size", bar_size)
    table.add_row("Selection Mode", mode)
    table.add_row("K Strikes", str(k_strikes) if mode == "atm" else "N/A")
    table.add_row("Pipeline", pipeline_name)
    table.add_row("Dataset", dataset)
    console.print(table)
    console.print()

    # Dry run mode
    if dry_run:
        console.print("[yellow]DRY RUN MODE - No data will be fetched[/yellow]")
        if earnings_date_parsed:
            console.print(f"[yellow]Would backfill earnings symbols options from {start_date} to {end_date}[/yellow]")
        else:
            console.print(f"[yellow]Would backfill {symbol} options from {start_date} to {end_date}[/yellow]")
        console.print("[yellow]Remove --dry-run to actually execute[/yellow]")
        return

    # Confirmation for large operations
    days = (end_date - start_date).days + 1
    if days > 90 or earnings_date_parsed:
        if earnings_date_parsed:
            console.print(f"[yellow]Large backfill: Earnings batch mode, {days} days[/yellow]")
        else:
            console.print(f"[yellow]Large backfill: {days} days[/yellow]")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    try:
        # Create params
        params = BackfillOptionsParams(
            underlying=symbol,
            spot_price=spot_price,
            earnings_date=earnings_date_parsed,
            earnings_symbols_filter=symbols_list,  # New: filter specific symbols in earnings mode
            auto_spot_price=earnings_date_parsed is not None,
            k_expirations=k_expirations,
            snapshot_date=snapshot_date_parsed,
            earnings_dataset_name=earnings_dataset,
            option_chains_dataset_name=option_chains_dataset,
            stocks_dataset_name=stocks_dataset,
            start_date=start_date,
            end_date=end_date,
            bar_size=bar_size,
            selection_mode=mode,
            k_strikes=k_strikes,
            min_dte=min_dte,
            max_dte=max_dte,
            pipeline_name=pipeline_name,
            dataset_name=dataset,
            use_delta=use_delta,
            client_id=client_id,
        )

        # Get connection config
        conn_config = get_connection_config(config_file)

        # Execute with progress bar
        console.print("[cyan]Starting backfill...[/cyan]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Backfilling options...", total=None)
            result = execute_backfill_options(params, connection_config=conn_config)

        # Display results
        console.print()
        if result.success:
            console.print(f"[green]✓ Backfill completed successfully![/green]")
            console.print(f"[cyan]Contracts processed:[/cyan] {result.contracts_processed}")
            console.print(f"[cyan]Total bars:[/cyan] {result.total_bars}")
            console.print(f"[cyan]Data saved to:[/cyan] {result.output_path}")
            console.print(f"[cyan]Duration:[/cyan] {result.duration_seconds:.1f}s")

            if result.warnings:
                console.print(f"\n[yellow]Warnings:[/yellow]")
                for warning in result.warnings:
                    console.print(f"  [yellow]⚠[/yellow] {warning}")
        else:
            console.print(f"[red]✗ Backfill failed: {result.error}[/red]")
            if result.warnings:
                for warning in result.warnings:
                    console.print(f"  [yellow]⚠[/yellow] {warning}")
            raise typer.Exit(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Backfill interrupted by user[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        if verbose:
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1)


@app.command()
def backfill_equity(
    symbols: Optional[List[str]] = typer.Argument(None, help="Stock symbols to backfill (or use --earnings-date)"),
    earnings_date: Optional[str] = typer.Option(
        None, "--earnings-date", help="Earnings date to backfill all symbols (YYYY-MM-DD, mutually exclusive with symbols)"
    ),
    has_options: bool = typer.Option(
        False, "--has-options", help="Filter to only symbols with option chain snapshots (requires --earnings-date or snapshot_date)"
    ),
    snapshot_date: Optional[str] = typer.Option(
        None, "--snapshot-date", help="Date to check for option snapshots (YYYY-MM-DD, defaults to earnings-date)"
    ),
    start: Optional[str] = typer.Option(
        None, "--start", help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="End date (YYYY-MM-DD, default: today)"
    ),
    bar_size: str = typer.Option("1 day", "--bar-size", "-b", help="Bar size"),
    pipeline_name: str = typer.Option("ib_stocks", "--pipeline-name", "--pipeline", help="Pipeline name"),
    dataset: str = typer.Option("stocks", "--dataset", help="Dataset name"),
    earnings_dataset: str = typer.Option("earnings", "--earnings-dataset", help="Earnings dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --pipeline-name instead"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
    # New options
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress INFO logs"),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="Write logs to file with rotation"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Output structured JSON logs"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview operation without fetching data or writing to database (validation only)"),
    client_id: Optional[int] = typer.Option(None, "--client-id", help="IB Gateway client ID (overrides config default)"),
    use_delta: bool = typer.Option(False, "--delta", help="Use Delta Lake format (ACID transactions, time travel)"),
):
    """
    Backfill equity bars with gap detection.

    Modes:
      1. Explicit symbols: Specify symbols directly
      2. Earnings batch: Load all symbols with earnings on a date

    Option filtering (--has-options):
      Filter to only symbols with option chain snapshots.
      Useful for option strategy backtesting to ensure underlying price data exists.

    Dry run (--dry-run):
      Validates parameters and shows what would be backfilled without:
      - Connecting to IB Gateway
      - Fetching any historical data
      - Writing to the database
      Use this to verify symbol count, date ranges, and configuration before running.

    Examples:
        # Backfill specific symbols
        dlt-ibapi backfill-equity AAPL MSFT GOOGL --bar-size "1 day"

        # Backfill all earnings symbols on a date
        dlt-ibapi backfill-equity --earnings-date 2025-11-13 --start 2025-01-01

        # Backfill only symbols with option contracts (for option backtesting)
        dlt-ibapi backfill-equity --earnings-date 2025-11-17 --has-options --start 2025-10-01

        # Preview operation first (dry run)
        dlt-ibapi backfill-equity --earnings-date 2025-11-17 --has-options --dry-run

        # Custom pipeline with verbose logging
        dlt-ibapi backfill-equity AAPL --pipeline-name my_stocks --verbose
    """
    from .cli import BackfillEquityParams, execute_backfill_equity
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

    # Validate mutual exclusivity
    if symbols and earnings_date:
        console.print("[red]Error: Cannot specify both symbols and --earnings-date. Use one or the other.[/red]")
        raise typer.Exit(1)
    if not symbols and not earnings_date:
        console.print("[red]Error: Must specify either symbols or --earnings-date.[/red]")
        raise typer.Exit(1)

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --pipeline-name instead.[/yellow]")
        pipeline_name = database.replace(".duckdb", "")

    # Parse dates
    start_date = datetime.strptime(start, "%Y-%m-%d").date() if start else date.today() - timedelta(days=30)
    end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()
    earnings_date_parsed = datetime.strptime(earnings_date, "%Y-%m-%d").date() if earnings_date else None
    snapshot_date_parsed = datetime.strptime(snapshot_date, "%Y-%m-%d").date() if snapshot_date else earnings_date_parsed

    # Filter by option availability if requested
    if has_options:
        if not snapshot_date_parsed:
            console.print("[red]Error: --has-options requires either --earnings-date or --snapshot-date[/red]")
            raise typer.Exit(1)

        from .repositories import OptionChainSnapshotReader
        from .cli.models import _get_default_database_path

        data_path = _get_default_database_path()
        option_reader = OptionChainSnapshotReader(str(data_path), "option_chains")

        # Get symbols with snapshots
        snapshots_df = option_reader.get_symbols_with_snapshots(snapshot_date=snapshot_date_parsed)

        if snapshots_df.empty:
            console.print(f"[yellow]No option chain snapshots found for {snapshot_date_parsed}[/yellow]")
            if earnings_date_parsed:
                console.print("[yellow]Run snapshot command first: dlt-ibapi snapshot capture --earnings-date {earnings_date}[/yellow]")
            raise typer.Exit(1)

        symbols_with_options = snapshots_df["symbol"].unique().tolist()
        console.print(f"[cyan]Found {len(symbols_with_options)} symbols with option snapshots on {snapshot_date_parsed}[/cyan]")

        # Filter the symbols list
        if symbols:
            # Filter explicit symbols
            symbols = [s for s in symbols if s.upper() in symbols_with_options]
            if not symbols:
                console.print("[yellow]None of the specified symbols have option snapshots[/yellow]")
                raise typer.Exit(1)
            console.print(f"[cyan]Filtered to {len(symbols)} symbols with options[/cyan]")
        elif earnings_date_parsed:
            # In earnings mode, load earnings symbols first, then filter
            from .repositories import EarningsCalendarReader

            earnings_reader = EarningsCalendarReader(str(data_path), earnings_dataset)
            earnings_df = earnings_reader.get_earnings_on_date(earnings_date_parsed)

            if earnings_df.empty:
                console.print(f"[yellow]No earnings found on {earnings_date_parsed}[/yellow]")
                raise typer.Exit(1)

            all_earnings_symbols = earnings_df["symbol"].unique().tolist()
            # Filter to only symbols with options
            symbols = [s for s in all_earnings_symbols if s in symbols_with_options]

            if not symbols:
                console.print(f"[yellow]No earnings symbols on {earnings_date_parsed} have option snapshots[/yellow]")
                raise typer.Exit(1)

            console.print(f"[cyan]Filtered {len(all_earnings_symbols)} earnings symbols to {len(symbols)} with options[/cyan]")
            # Convert to explicit symbol mode
            earnings_date = None
            earnings_date_parsed = None

    # Display plan
    mode_desc = f"earnings on {earnings_date_parsed}" if earnings_date_parsed else f"{len(symbols)} symbols"
    console.print(f"\n[bold cyan]{'DRY RUN: ' if dry_run else ''}Backfilling equity bars for {mode_desc}[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    if earnings_date_parsed:
        table.add_row("Mode", "Earnings Batch")
        table.add_row("Earnings Date", str(earnings_date_parsed))
    else:
        table.add_row("Mode", "Explicit Symbols")
        table.add_row("Symbols", ", ".join(symbols))
    table.add_row("Date Range", f"{start_date} to {end_date}")
    table.add_row("Bar Size", bar_size)
    table.add_row("Pipeline", pipeline_name)
    table.add_row("Dataset", dataset)
    table.add_row("Days", str((end_date - start_date).days + 1))
    console.print(table)
    console.print()

    # Dry run mode
    if dry_run:
        console.print("[yellow]DRY RUN MODE - No data will be fetched[/yellow]")
        if earnings_date_parsed:
            console.print(f"[yellow]Would backfill earnings symbols from {start_date} to {end_date}[/yellow]")
        else:
            console.print(f"[yellow]Would backfill {len(symbols)} symbols from {start_date} to {end_date}[/yellow]")
        console.print("[yellow]Remove --dry-run to actually execute[/yellow]")
        return

    # Confirmation for large operations
    days = (end_date - start_date).days + 1
    num_symbols = len(symbols) if symbols else 0  # Will be determined by earnings loader
    if (symbols and len(symbols) > 10) or days > 90 or earnings_date_parsed:
        if earnings_date_parsed:
            console.print(f"[yellow]Large backfill: Earnings batch mode, {days} days[/yellow]")
        else:
            console.print(f"[yellow]Large backfill: {num_symbols} symbols, {days} days[/yellow]")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    try:
        # Create params
        params = BackfillEquityParams(
            symbols=symbols,
            earnings_date=earnings_date_parsed,
            earnings_dataset_name=earnings_dataset,
            start_date=start_date,
            end_date=end_date,
            bar_size=bar_size,
            pipeline_name=pipeline_name,
            dataset_name=dataset,
            use_delta=use_delta,
            client_id=client_id,
        )

        # Get connection config
        conn_config = get_connection_config(config_file)

        # Execute with progress bar
        console.print("[cyan]Starting backfill...[/cyan]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            total_symbols = len(symbols) if symbols else None  # None = indeterminate
            task = progress.add_task("Backfilling...", total=total_symbols)
            result = execute_backfill_equity(params, connection_config=conn_config)
            progress.update(task, completed=total_symbols or len(result.symbols_processed))

        # Display results
        console.print()
        if result.success:
            console.print(f"[green]✓ Backfill completed successfully![/green]")
            total_count = len(symbols) if symbols else len(result.symbols_processed)
            console.print(f"[cyan]Symbols processed:[/cyan] {len(result.symbols_processed)}/{total_count}")
            console.print(f"[cyan]Data saved to:[/cyan] {result.output_path}")
            console.print(f"[cyan]Duration:[/cyan] {result.duration_seconds:.1f}s")

            if result.warnings:
                console.print(f"\n[yellow]Warnings:[/yellow]")
                for warning in result.warnings:
                    console.print(f"  [yellow]⚠[/yellow] {warning}")

            # Display summary
            from .repositories import EquityBarsReader
            reader = EquityBarsReader(str(params.database_path), dataset)
            summary = reader.get_symbols_summary(bar_size=bar_size)

            if not summary.empty:
                console.print()
                table = Table(title="Backfill Summary")
                table.add_column("Symbol", style="cyan")
                table.add_column("Bar Count", justify="right")
                table.add_column("First Bar", style="dim")
                table.add_column("Last Bar", style="dim")

                for _, row in summary.iterrows():
                    if row['symbol'] in result.symbols_processed:
                        table.add_row(
                            row['symbol'],
                            str(int(row['bar_count'])),
                            str(row['first_bar'].date()),
                            str(row['last_bar'].date())
                        )

                console.print(table)
        else:
            console.print(f"[red]✗ Backfill failed: {result.error}[/red]")
            if result.warnings:
                for warning in result.warnings:
                    console.print(f"  [yellow]⚠[/yellow] {warning}")
            raise typer.Exit(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Backfill interrupted by user[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        if verbose:
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1)



@app.command()
def list_snapshots(
    symbol: Optional[str] = typer.Argument(None, help="Symbol to list snapshots for"),
    data_dir: str = typer.Option("./data", "--data-dir", help="Data directory path"),
    dataset: str = typer.Option("option_chains", "--dataset", help="Dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --data-dir instead"),
):
    """
    List available option chain snapshots.

    Example:
        dlt-ibapi list-snapshots AAPL
        dlt-ibapi list-snapshots --data-dir ./data --dataset option_chains
    """
    from .repositories import OptionChainSnapshotReader

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --data-dir instead.[/yellow]")
        data_dir = database.replace(".duckdb", "")

    console.print(f"\n[bold cyan]Available Option Chain Snapshots[/bold cyan]\n")

    try:
        reader = OptionChainSnapshotReader(data_dir, dataset)

        if symbol:
            # List snapshots for specific symbol
            snapshots = reader.get_available_snapshots(symbol)

            if not snapshots:
                console.print(f"No snapshots found for {symbol}")
                return

            console.print(f"[green]{symbol}[/green] ({len(snapshots)} snapshots):")
            for snap_date in sorted(snapshots):
                console.print(f"  - {snap_date}")

        else:
            # List all snapshots
            all_data = reader.load(columns=["underlying", "as_of"])
            if all_data.empty:
                console.print("No snapshots found")
                return

            by_symbol = all_data.groupby("underlying")["as_of"].apply(list).to_dict()

            for sym, dates in sorted(by_symbol.items()):
                console.print(f"[green]{sym}[/green] ({len(dates)} snapshots):")
                for snap_date in sorted(dates)[:5]:  # Show first 5
                    console.print(f"  - {snap_date}")
                if len(dates) > 5:
                    console.print(f"  ... and {len(dates) - 5} more")

    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@app.command()
def stats(
    data_dir: str = typer.Argument(..., help="Data directory path (e.g., './data')"),
    dataset: str = typer.Option(..., "--dataset", "-d", help="Dataset name (stocks, options, option_chains)"),
    table: Optional[str] = typer.Option(None, "--table", "-t", help="Specific table to analyze"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use data_dir instead"),
):
    """
    Show Parquet data statistics (table sizes, date ranges, contract counts).

    Example:
        dlt-ibapi stats ./data --dataset stocks
        dlt-ibapi stats ./data --dataset options
        dlt-ibapi stats ./data --dataset option_chains
        dlt-ibapi stats ./data --dataset option_chains --table option_chain_snapshot
    """
    from .cli import StatsParams, execute_stats

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use data_dir argument instead.[/yellow]")
        data_dir = database

    console.print(f"\n[bold cyan]Parquet Data Statistics[/bold cyan]\n")
    console.print(f"Data directory: {data_dir}")
    console.print(f"Dataset:        {dataset}")
    if table:
        console.print(f"Table:          {table}")
    console.print()

    try:
        # Create params
        params = StatsParams(
            database_path=Path(data_dir),
            dataset_name=dataset,
            table_name=table,
        )

        # Execute using business logic
        result = execute_stats(params)

        if not result.success:
            console.print(f"[red]✗[/red] {result.error}")

            # If dataset not found, suggest available datasets
            data_path = Path(data_dir)
            if data_path.exists() and "does not exist" in result.error:
                available_datasets = [d.name for d in data_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
                if available_datasets:
                    console.print(f"\n[yellow]Available datasets in {data_dir}:[/yellow]")
                    for ds in sorted(available_datasets):
                        console.print(f"  - {ds}")
                    console.print(f"\n[cyan]Try:[/cyan] dlt-ibapi stats {data_dir} --dataset {available_datasets[0]}")
                else:
                    console.print(f"\n[yellow]No datasets found in {data_dir}[/yellow]")
                    console.print("[cyan]Common datasets: stocks, options, option_chains[/cyan]")

            raise typer.Exit(1)

        if not result.tables:
            console.print(f"[dim]No tables found in dataset '{dataset}'[/dim]")

            # Suggest available datasets
            data_path = Path(data_dir)
            if data_path.exists():
                available_datasets = [d.name for d in data_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
                if available_datasets and dataset not in available_datasets:
                    console.print(f"\n[yellow]Did you mean one of these datasets?[/yellow]")
                    for ds in sorted(available_datasets):
                        console.print(f"  - {ds}")
            return

        # Display results
        for table_stats in result.tables:
            console.print(f"[green]{table_stats.table_name}[/green]")
            console.print(f"  Rows: {table_stats.row_count:,}")

            if table_stats.date_range:
                console.print(f"  Date range: {table_stats.date_range}")

            if table_stats.symbols:
                if len(table_stats.symbols) <= 10:
                    console.print(f"  Symbols: {', '.join(table_stats.symbols)}")
                else:
                    console.print(f"  Symbols: {len(table_stats.symbols)} ({', '.join(table_stats.symbols[:5])}, ...)")

            console.print(f"  Columns: {len(table_stats.columns)}")
            console.print()

        console.print(f"[dim]Total: {result.total_tables} table(s) analyzed in {result.duration_seconds:.2f}s[/dim]")

    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@app.command()
def load_earnings(
    json_file: str = typer.Argument(..., help="Path to earnings JSON file"),
    pipeline_name: str = typer.Option("earnings_loader", "--pipeline-name", help="Pipeline name"),
    dataset: str = typer.Option("earnings", "--dataset", help="Dataset name"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="Filter start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="Filter end date (YYYY-MM-DD)"),
    symbols: Optional[List[str]] = typer.Option(None, "--symbols", help="Filter symbols"),
):
    """
    Load earnings calendar from Nasdaq JSON file into Parquet.

    Example:
        dlt-ibapi load-earnings /path/to/earnings_2025-11-13.txt
        dlt-ibapi load-earnings earnings.json --symbols AAPL MSFT
        dlt-ibapi load-earnings earnings.json --start-date 2025-11-01 --end-date 2025-11-30
    """
    from .earnings import load_earnings_from_json

    console.print(f"\n[bold cyan]Loading Earnings Calendar[/bold cyan]\n")
    console.print(f"JSON file:  {json_file}")
    console.print(f"Pipeline:   {pipeline_name}")
    console.print(f"Dataset:    {dataset}\n")

    try:
        # Parse date filters if provided
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

        # Get data path from storage config
        from .cli.models import _get_default_database_path
        data_path = _get_default_database_path()

        # Create pipeline
        pipeline = dlt.pipeline(
            pipeline_name=pipeline_name,
            destination=dlt.destinations.filesystem(bucket_url=str(data_path)),
            dataset_name=dataset,
        )

        # Load earnings
        with console.status("[bold green]Loading earnings from JSON..."):
            data = load_earnings_from_json(
                json_file=json_file,
                start_date=start,
                end_date=end,
                symbols=symbols,
            )

            info = pipeline.run(data, loader_file_format="parquet")

        if info.has_failed_jobs:
            console.print("[red]✗[/red] Load failed!")
            raise typer.Exit(1)

        console.print("[green]✓[/green] Earnings loaded successfully!\n")

        # Show summary
        from .repositories import EarningsCalendarReader
        from .cli.models import _get_default_database_path
        data_path = _get_default_database_path()
        reader = EarningsCalendarReader(str(data_path), dataset)

        total = reader.count_earnings()
        min_date, max_date = reader.get_date_range()
        symbols_count = len(reader.get_available_symbols())

        console.print(f"[cyan]Total earnings:[/cyan] {total}")
        console.print(f"[cyan]Date range:[/cyan] {min_date} to {max_date}")
        console.print(f"[cyan]Symbols:[/cyan] {symbols_count}")

    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@app.command()
def list_earnings(
    days_ahead: int = typer.Option(7, "--days-ahead", "-d", help="Days ahead to search"),
    symbols: Optional[List[str]] = typer.Option(None, "--symbols", "-s", help="Filter by symbols"),
    earnings_time: Optional[str] = typer.Option(None, "--time", "-t", help="Filter by time (PRE_MARKET, AFTER_HOURS)"),
    dataset: str = typer.Option("earnings", "--dataset", help="Dataset name"),
):
    """
    List upcoming earnings from stored data.

    Example:
        dlt-ibapi list-earnings
        dlt-ibapi list-earnings --days-ahead 14
        dlt-ibapi list-earnings --symbols AAPL MSFT GOOGL
        dlt-ibapi list-earnings --days-ahead 30 --time PRE_MARKET
    """
    from .repositories import EarningsCalendarReader
    from rich.table import Table
    import traceback

    # Get structured logger from centralized logging utility
    logger = get_logger(__name__)

    console.print(f"\n[bold cyan]Upcoming Earnings ({days_ahead} days)[/bold cyan]\n")

    try:
        # Load storage config to get data path
        from .cli.models import _get_default_database_path
        data_path = _get_default_database_path()

        logger.info(
            "list_earnings.start",
            days_ahead=days_ahead,
            dataset=dataset,
            symbols=symbols,
            earnings_time=earnings_time,
            data_path=str(data_path),
        )

        reader = EarningsCalendarReader(str(data_path), dataset)
        logger.debug("list_earnings.reader_created", dataset=dataset)

        # Get upcoming earnings
        earnings = reader.get_upcoming_earnings(
            days_ahead=days_ahead,
            symbols=symbols,
            earnings_time=earnings_time,
        )

        logger.info(
            "list_earnings.data_loaded",
            earnings_count=len(earnings),
            columns=list(earnings.columns) if not earnings.empty else [],
        )

        if earnings.empty:
            logger.warning("list_earnings.no_data", days_ahead=days_ahead)
            console.print("[dim]No upcoming earnings found[/dim]")
            return

        # Display as table
        table = Table(title=f"Upcoming Earnings (Next {days_ahead} Days)")
        table.add_column("Symbol", style="cyan")
        table.add_column("Date", style="green")
        table.add_column("Time", style="yellow")
        table.add_column("Company", style="dim")
        table.add_column("EPS Forecast", justify="right")

        for idx, row in earnings.iterrows():
            try:
                # Get EPS forecast safely
                eps_forecast = row.get("eps_forecast")
                eps_display = "N/A"

                logger.debug(
                    "list_earnings.row_processing",
                    index=idx,
                    symbol=row.get("symbol"),
                    eps_forecast_raw=eps_forecast,
                    eps_forecast_type=type(eps_forecast).__name__,
                )

                # Check if eps_forecast is not None and is a number
                if eps_forecast is not None:
                    try:
                        # Try to convert to float and check if it's valid
                        eps_value = float(eps_forecast)
                        if not (eps_value != eps_value):  # Check for NaN (NaN != NaN is True)
                            eps_display = f"${eps_value:.2f}"
                    except (ValueError, TypeError) as conv_err:
                        logger.warning(
                            "list_earnings.eps_conversion_failed",
                            symbol=row.get("symbol"),
                            eps_forecast=eps_forecast,
                            error=str(conv_err),
                        )

                table.add_row(
                    row["symbol"],
                    str(row["earnings_date"]),
                    row.get("earnings_time", "UNKNOWN"),
                    row.get("company_name", "")[:30],  # Truncate long names
                    eps_display,
                )
            except Exception as row_err:
                logger.error(
                    "list_earnings.row_error",
                    index=idx,
                    symbol=row.get("symbol"),
                    error=str(row_err),
                    traceback=traceback.format_exc(),
                )
                # Continue with other rows even if one fails
                continue

        console.print(table)
        console.print(f"\n[dim]Total: {len(earnings)} earnings event(s)[/dim]")

        logger.info("list_earnings.complete", earnings_count=len(earnings))

    except ValueError as e:
        logger.error("list_earnings.value_error", error=str(e), traceback=traceback.format_exc())
        if "does not exist" in str(e):
            console.print(f"[red]✗[/red] Earnings dataset not found: {dataset}")
            console.print(f"\n[yellow]Load earnings data first:[/yellow]")
            console.print(f"  dlt-ibapi load-earnings /path/to/earnings.json")
        else:
            console.print(f"\n[red bold]✗ ValueError:[/red bold] {str(e)}")
            console.print(f"[dim]See logs for details[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        logger.error(
            "list_earnings.error",
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
        )
        console.print(f"\n[red bold]✗ Error ({type(e).__name__}):[/red bold] {str(e)}")
        console.print(f"[dim]Use --verbose for detailed logs[/dim]")
        raise typer.Exit(1)


@app.command()
def resolve_contracts(
    symbols: Optional[List[str]] = typer.Argument(
        None,
        help="Symbols to resolve (e.g., AAPL MSFT GOOGL)",
    ),
    earnings_date: Optional[str] = typer.Option(
        None,
        "--earnings-date",
        help="Load symbols from earnings on this date (YYYY-MM-DD)",
    ),
    earnings_file: Optional[Path] = typer.Option(
        None,
        "--earnings-file",
        help="Load symbols from earnings JSON file",
    ),
    sec_type: str = typer.Option(
        "STK",
        "--sec-type",
        help="Security type: STK for equities, OPT for options",
    ),
    snapshot_date: Optional[str] = typer.Option(
        None,
        "--snapshot-date",
        help="Load option contracts from snapshot on this date (YYYY-MM-DD) [OPT only]",
    ),
    underlying: Optional[str] = typer.Option(
        None,
        "--underlying",
        help="Filter by underlying symbol [OPT only]",
    ),
    database_path: Optional[Path] = typer.Option(
        None,
        "--database-path",
        help="Path to data directory (default: from storage_config.yaml)",
    ),
    cache_path: Path = typer.Option(
        Path(".dlt-ibapi/cache"),
        "--cache-path",
        help="Path to contract cache",
    ),
    exchange: str = typer.Option(
        "SMART",
        "--exchange",
        help="Exchange for contract resolution",
    ),
    currency: str = typer.Option(
        "USD",
        "--currency",
        help="Currency for contract resolution",
    ),
):
    """
    Pre-populate contract cache by resolving symbols/contracts to IB contract details.

    Supports both equity (STK) and option (OPT) contract resolution.

    This command resolves symbols/contracts to Interactive Brokers contract details and
    caches them for faster subsequent operations. Useful for:
    - Pre-resolving earnings symbols before snapshot/backfill
    - Pre-resolving option contracts from snapshots before backfill
    - Validating symbols/contracts before expensive operations
    - Building contract cache for offline use

    Examples:
        # Resolve equity symbols
        dlt-ibapi resolve-contracts AAPL MSFT GOOGL

        # Resolve symbols from earnings calendar
        dlt-ibapi resolve-contracts --earnings-date 2025-11-13

        # Resolve option contracts from snapshot
        dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13

        # Resolve options for specific underlying
        dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13 --underlying AAPL

    The command will:
    - Skip contracts already in cache
    - Handle errors gracefully (log and continue)
    - Report success/failure summary
    """
    from dlt_ibapi.cli.resolve import execute_resolve_contracts
    from dlt_ibapi.cli.models import ResolveContractsParams

    try:
        # Parse earnings date
        parsed_earnings_date = None
        if earnings_date:
            try:
                parsed_earnings_date = datetime.strptime(earnings_date, "%Y-%m-%d").date()
            except ValueError:
                console.print(f"[red]Invalid date format:[/red] {earnings_date}")
                console.print("Expected format: YYYY-MM-DD")
                raise typer.Exit(1)

        # Parse snapshot date
        parsed_snapshot_date = None
        if snapshot_date:
            try:
                parsed_snapshot_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
            except ValueError:
                console.print(f"[red]Invalid date format:[/red] {snapshot_date}")
                console.print("Expected format: YYYY-MM-DD")
                raise typer.Exit(1)

        # Create params (database_path will use default from storage config if None)
        from dlt_ibapi.cli.models import _get_default_database_path
        params = ResolveContractsParams(
            symbols=symbols,
            earnings_date=parsed_earnings_date,
            earnings_file=earnings_file,
            sec_type=sec_type,
            snapshot_date=parsed_snapshot_date,
            underlying=underlying,
            database_path=database_path if database_path else _get_default_database_path(),
            cache_path=cache_path,
            exchange=exchange,
            currency=currency,
        )

        # Execute
        console.print("\n[bold cyan]Resolving contracts...[/bold cyan]\n")
        result = execute_resolve_contracts(params)

        # Display results
        if result.error:
            console.print(f"[red bold]✗ Error:[/red bold] {result.error}")
            raise typer.Exit(1)

        # Summary table
        table = Table(title="Contract Resolution Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Total Requested", str(result.total_requested))
        table.add_row("Resolved (New)", str(len(result.resolved)), style="green")
        table.add_row("Skipped (Cached)", str(len(result.skipped)), style="yellow")
        table.add_row("Failed", str(len(result.failed)), style="red" if result.failed else "white")
        table.add_row("Duration", f"{result.duration_seconds:.2f}s")
        table.add_row("Cache Path", str(result.cache_path))

        console.print(table)

        # Resolved contracts
        if result.resolved:
            console.print("\n[bold green]✓ Resolved Contracts:[/bold green]")
            resolved_table = Table()
            resolved_table.add_column("Symbol", style="cyan")
            resolved_table.add_column("ConID", style="white")
            resolved_table.add_column("Exchange", style="yellow")
            resolved_table.add_column("Company", style="white")

            for contract in result.resolved:
                resolved_table.add_row(
                    contract.symbol,
                    str(contract.conid),
                    contract.exchange,
                    contract.long_name or "N/A",
                )

            console.print(resolved_table)

        # Skipped symbols
        if result.skipped and len(result.skipped) <= 20:
            console.print(f"\n[bold yellow]Skipped (already cached):[/bold yellow] {', '.join(result.skipped)}")
        elif result.skipped:
            console.print(f"\n[bold yellow]Skipped:[/bold yellow] {len(result.skipped)} symbols already cached")

        # Failed symbols
        if result.failed:
            console.print("\n[bold red]✗ Failed Contracts:[/bold red]")
            failed_table = Table()
            failed_table.add_column("Symbol", style="cyan")
            failed_table.add_column("Error", style="red")

            for symbol, error in result.failed.items():
                # Truncate long error messages
                error_short = error if len(error) < 80 else error[:77] + "..."
                failed_table.add_row(symbol, error_short)

            console.print(failed_table)

        # Exit code
        if result.failed:
            console.print(f"\n[yellow]Warning: {len(result.failed)} symbols failed to resolve[/yellow]")
            raise typer.Exit(1)
        else:
            console.print("\n[green]✓ All contracts resolved successfully[/green]")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@app.command()
def deduplicate(
    database_path: Path = typer.Option(Path("./data"), "--database-path", help="Path to data directory"),
    dataset: str = typer.Option(..., "--dataset", help="Dataset to deduplicate (options, stocks, earnings, option_chains)"),
    table: Optional[str] = typer.Option(None, "--table", help="Specific table name (default: all tables in dataset)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes"),
    no_backup: bool = typer.Option(False, "--no-backup", help="Skip backup before deduplication"),
):
    """
    Deduplicate tables by removing duplicate rows based on primary keys.

    When duplicates exist, keeps the row from the most recent DLT load.
    Creates backups by default before making changes.

    Examples:
        # Analyze duplicates in options dataset (dry-run)
        dlt-ibapi deduplicate --dataset options --dry-run

        # Deduplicate all tables in options dataset
        dlt-ibapi deduplicate --dataset options

        # Deduplicate specific table
        dlt-ibapi deduplicate --dataset options --table option_bars_backfill

        # Deduplicate without backup (faster but less safe)
        dlt-ibapi deduplicate --dataset options --no-backup
    """
    from dlt_ibapi.maintenance import deduplicate_delta_table, deduplicate_dataset
    from rich.table import Table

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

    try:
        if dataset not in DATASET_CONFIGS:
            console.print(f"[red]Error: Unknown dataset '{dataset}'[/red]")
            console.print(f"Available datasets: {', '.join(DATASET_CONFIGS.keys())}")
            raise typer.Exit(1)

        create_backup = not no_backup

        # Show mode
        mode_str = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]EXECUTION[/green]"
        console.print(f"\n{mode_str} - Deduplication for dataset: [cyan]{dataset}[/cyan]")
        console.print(f"Database path: {database_path}\n")

        if table:
            # Deduplicate specific table
            table_configs = DATASET_CONFIGS[dataset]
            table_config = next((tc for tc in table_configs if tc[0] == table), None)

            if not table_config:
                console.print(f"[red]Error: Table '{table}' not found in dataset '{dataset}'[/red]")
                console.print(f"Available tables: {', '.join([tc[0] for tc in table_configs])}")
                raise typer.Exit(1)

            table_name, primary_key = table_config

            console.print(f"Analyzing table: [cyan]{table_name}[/cyan]...")

            result = deduplicate_delta_table(
                data_dir=str(database_path),
                dataset=dataset,
                table_name=table_name,
                primary_key=primary_key,
                dry_run=dry_run,
                create_backup=create_backup,
            )

            console.print(f"\n{result}\n")

            if result.duplicates_removed > 0 and not dry_run:
                console.print("[green]✓ Deduplication completed successfully[/green]")
            elif result.duplicates_removed > 0 and dry_run:
                console.print("[yellow]Run without --dry-run to actually remove duplicates[/yellow]")
            else:
                console.print("[green]✓ No duplicates found[/green]")

        else:
            # Deduplicate all tables in dataset
            table_configs = DATASET_CONFIGS[dataset]
            console.print(f"Analyzing {len(table_configs)} table(s)...\n")

            results = deduplicate_dataset(
                data_dir=str(database_path),
                dataset=dataset,
                table_configs=table_configs,
                dry_run=dry_run,
                create_backup=create_backup,
            )

            # Display summary table
            summary_table = Table(title=f"Deduplication Summary - {dataset}")
            summary_table.add_column("Table", style="cyan")
            summary_table.add_column("Rows Before", justify="right")
            summary_table.add_column("Duplicates", justify="right", style="yellow")
            summary_table.add_column("Rows After", justify="right")
            summary_table.add_column("% Duped", justify="right")
            summary_table.add_column("Time (s)", justify="right")

            total_before = 0
            total_after = 0
            total_dupes = 0

            for result in results:
                summary_table.add_row(
                    result.table_name,
                    f"{result.rows_before:,}",
                    f"{result.duplicates_removed:,}",
                    f"{result.rows_after:,}",
                    f"{result.duplicate_percentage:.2f}%",
                    f"{result.execution_time_sec:.2f}",
                )
                total_before += result.rows_before
                total_after += result.rows_after
                total_dupes += result.duplicates_removed

            # Add totals row
            total_pct = 100.0 * total_dupes / total_before if total_before > 0 else 0.0
            summary_table.add_section()
            summary_table.add_row(
                "[bold]TOTAL[/bold]",
                f"[bold]{total_before:,}[/bold]",
                f"[bold]{total_dupes:,}[/bold]",
                f"[bold]{total_after:,}[/bold]",
                f"[bold]{total_pct:.2f}%[/bold]",
                "",
            )

            console.print(summary_table)

            if total_dupes > 0 and not dry_run:
                console.print("\n[green]✓ Deduplication completed successfully[/green]")
            elif total_dupes > 0 and dry_run:
                console.print("\n[yellow]Run without --dry-run to actually remove duplicates[/yellow]")
            else:
                console.print("\n[green]✓ No duplicates found in any tables[/green]")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@app.command()
def validate(
    database_path: Path = typer.Option(Path("./data"), "--database-path", help="Path to data directory"),
    dataset: str = typer.Option(..., "--dataset", help="Dataset to validate"),
    check_duplicates: bool = typer.Option(True, "--check-duplicates", help="Check for duplicate rows"),
):
    """
    Validate data quality in datasets.

    Checks for issues like duplicates, missing data, or inconsistencies.

    Examples:
        dlt-ibapi validate --dataset options
        dlt-ibapi validate --dataset stocks --check-duplicates
    """
    from dlt_ibapi.maintenance import get_duplicate_report
    from rich.table import Table

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

    try:
        if dataset not in DATASET_CONFIGS:
            console.print(f"[red]Error: Unknown dataset '{dataset}'[/red]")
            raise typer.Exit(1)

        console.print(f"\n[cyan]Validating dataset: {dataset}[/cyan]")
        console.print(f"Database path: {database_path}\n")

        if check_duplicates:
            table_configs = DATASET_CONFIGS[dataset]

            validation_table = Table(title="Duplicate Analysis")
            validation_table.add_column("Table", style="cyan")
            validation_table.add_column("Total Rows", justify="right")
            validation_table.add_column("Unique Rows", justify="right")
            validation_table.add_column("Duplicates", justify="right", style="yellow")
            validation_table.add_column("% Duped", justify="right")

            has_duplicates = False

            for table_name, primary_key in table_configs:
                try:
                    report = get_duplicate_report(
                        data_dir=str(database_path),
                        dataset=dataset,
                        table_name=table_name,
                        primary_key=primary_key,
                    )

                    style = "red" if report["duplicate_pct"] > 0 else "green"

                    validation_table.add_row(
                        table_name,
                        f"{report['total_rows']:,}",
                        f"{report['unique_rows']:,}",
                        f"[{style}]{report['duplicate_rows']:,}[/{style}]",
                        f"[{style}]{report['duplicate_pct']:.2f}%[/{style}]",
                    )

                    if report["duplicate_rows"] > 0:
                        has_duplicates = True

                except Exception as e:
                    validation_table.add_row(
                        table_name,
                        "[red]ERROR[/red]",
                        "-",
                        "-",
                        f"[red]{str(e)}[/red]",
                    )

            console.print(validation_table)

            if has_duplicates:
                console.print("\n[yellow]⚠ Duplicates detected. Run 'dlt-ibapi deduplicate' to clean.[/yellow]")
            else:
                console.print("\n[green]✓ No duplicates found[/green]")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)


@app.command()
def version():
    """Show dlt-ibapi version."""
    from . import __version__
    console.print(f"dlt-ibapi version: {__version__}")


# ============================================================================
# Strategy Commands
# ============================================================================


def main():
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
