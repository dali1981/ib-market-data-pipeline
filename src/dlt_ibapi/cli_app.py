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

app = typer.Typer(
    name="dlt-ibapi",
    help="CLI for Interactive Brokers DLT connector",
    add_completion=False,
)
console = Console()


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


@app.command()
def snapshot(
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
            reader = OptionChainSnapshotReader("data", dataset)
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


@app.command()
def backfill_options(
    symbol: str = typer.Argument(..., help="Underlying symbol (e.g., AAPL)"),
    spot_price: float = typer.Argument(..., help="Current spot price"),
    start: Optional[str] = typer.Option(
        None, "--start", help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="End date (YYYY-MM-DD, default: today)"
    ),
    bar_size: str = typer.Option("1 day", "--bar-size", "-b", help="Bar size"),
    mode: str = typer.Option("atm", "--mode", "-m", help="Selection mode: atm, moneyness, delta, all"),
    k_strikes: int = typer.Option(5, "--k-strikes", "-k", help="K strikes for ATM mode"),
    min_dte: int = typer.Option(7, "--min-dte", help="Minimum days to expiration"),
    max_dte: int = typer.Option(60, "--max-dte", help="Maximum days to expiration"),
    pipeline_name: str = typer.Option("ib_options", "--pipeline-name", "--pipeline", help="Pipeline name"),
    dataset: str = typer.Option("options", "--dataset", help="Dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --pipeline-name instead"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
    # New options
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress INFO logs"),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="Write logs to file with rotation"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Output structured JSON logs"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without doing it"),
):
    """
    Backfill option bars with gap detection.

    Example:
        dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
        dlt-ibapi backfill-options AAPL 150.0 --pipeline-name my_options --verbose
        dlt-ibapi backfill-options AAPL 150.0 --dry-run
    """
    from .utils.logging import setup_logging
    from .cli import BackfillOptionsParams, execute_backfill_options
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

    # Setup logging
    setup_logging(
        level="INFO",
        log_file=log_file,
        verbose=verbose,
        quiet=quiet or dry_run,
        json_logs=json_logs,
    )

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --pipeline-name instead.[/yellow]")
        pipeline_name = database.replace(".duckdb", "")

    # Parse dates
    start_date = datetime.strptime(start, "%Y-%m-%d").date() if start else date.today() - timedelta(days=30)
    end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()

    # Validate selection mode
    valid_modes = ["atm", "moneyness", "delta", "all"]
    if mode not in valid_modes:
        console.print(f"[red]✗ Invalid mode: {mode}. Choose from: {', '.join(valid_modes)}[/red]")
        raise typer.Exit(1)

    # Display plan
    console.print(f"\n[bold cyan]{'DRY RUN: ' if dry_run else ''}Backfilling option bars for {symbol}[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Underlying", f"{symbol} @ ${spot_price}")
    table.add_row("Date Range", f"{start_date} to {end_date}")
    table.add_row("Bar Size", bar_size)
    table.add_row("Selection Mode", mode)
    table.add_row("K Strikes", str(k_strikes) if mode == "atm" else "N/A")
    table.add_row("DTE Range", f"{min_dte} to {max_dte}")
    table.add_row("Pipeline", pipeline_name)
    table.add_row("Dataset", dataset)
    console.print(table)
    console.print()

    # Dry run mode
    if dry_run:
        console.print("[yellow]DRY RUN MODE - No data will be fetched[/yellow]")
        console.print(f"[yellow]Would backfill {symbol} options from {start_date} to {end_date}[/yellow]")
        console.print("[yellow]Remove --dry-run to actually execute[/yellow]")
        return

    # Confirmation for large operations
    days = (end_date - start_date).days + 1
    if days > 90:
        console.print(f"[yellow]Large backfill: {days} days[/yellow]")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    try:
        # Create params
        params = BackfillOptionsParams(
            underlying=symbol,
            spot_price=spot_price,
            start_date=start_date,
            end_date=end_date,
            bar_size=bar_size,
            selection_mode=mode,
            k_strikes=k_strikes,
            min_dte=min_dte,
            max_dte=max_dte,
            pipeline_name=pipeline_name,
            dataset_name=dataset,
            database_path=Path("data"),
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
    symbols: List[str] = typer.Argument(..., help="Stock symbols to backfill"),
    start: Optional[str] = typer.Option(
        None, "--start", help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="End date (YYYY-MM-DD, default: today)"
    ),
    bar_size: str = typer.Option("1 day", "--bar-size", "-b", help="Bar size"),
    pipeline_name: str = typer.Option("ib_stocks", "--pipeline-name", "--pipeline", help="Pipeline name"),
    dataset: str = typer.Option("stocks", "--dataset", help="Dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --pipeline-name instead"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
    # New options
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress INFO logs"),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="Write logs to file with rotation"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Output structured JSON logs"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without doing it"),
):
    """
    Backfill equity bars with gap detection.

    Example:
        dlt-ibapi backfill-equity AAPL MSFT GOOGL --bar-size "1 day"
        dlt-ibapi backfill-equity AAPL --pipeline-name my_stocks --verbose
        dlt-ibapi backfill-equity AAPL MSFT --dry-run
    """
    from .utils.logging import setup_logging
    from .cli import BackfillEquityParams, execute_backfill_equity
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

    # Setup logging
    setup_logging(
        level="INFO",
        log_file=log_file,
        verbose=verbose,
        quiet=quiet or dry_run,  # Suppress logs in dry-run
        json_logs=json_logs,
    )

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --pipeline-name instead.[/yellow]")
        pipeline_name = database.replace(".duckdb", "")

    # Parse dates
    start_date = datetime.strptime(start, "%Y-%m-%d").date() if start else date.today() - timedelta(days=30)
    end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()

    # Display plan
    console.print(f"\n[bold cyan]{'DRY RUN: ' if dry_run else ''}Backfilling equity bars for {len(symbols)} symbols[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
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
        console.print(f"[yellow]Would backfill {len(symbols)} symbols from {start_date} to {end_date}[/yellow]")
        console.print("[yellow]Remove --dry-run to actually execute[/yellow]")
        return

    # Confirmation for large operations
    days = (end_date - start_date).days + 1
    if len(symbols) > 10 or days > 90:
        console.print(f"[yellow]Large backfill: {len(symbols)} symbols, {days} days[/yellow]")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    try:
        # Create params
        params = BackfillEquityParams(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            bar_size=bar_size,
            pipeline_name=pipeline_name,
            dataset_name=dataset,
            database_path=Path("data"),
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
            task = progress.add_task("Backfilling...", total=len(symbols))
            result = execute_backfill_equity(params, connection_config=conn_config)
            progress.update(task, completed=len(symbols))

        # Display results
        console.print()
        if result.success:
            console.print(f"[green]✓ Backfill completed successfully![/green]")
            console.print(f"[cyan]Symbols processed:[/cyan] {len(result.symbols_processed)}/{len(symbols)}")
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
def backtest_earnings_spreads(
    strategy: str = typer.Option(
        "iv_based",
        "--strategy",
        "-s",
        help="Strategy type: generic_calendar, pre_earnings, or iv_based",
    ),
    symbols: List[str] = typer.Option(
        ["AAPL", "MSFT"],
        "--symbols",
        help="Underlying symbols to trade",
    ),
    start_date: str = typer.Option(
        "2023-01-01",
        "--start-date",
        help="Backtest start date (YYYY-MM-DD)",
    ),
    end_date: str = typer.Option(
        "2024-12-31",
        "--end-date",
        help="Backtest end date (YYYY-MM-DD)",
    ),
    initial_capital: float = typer.Option(
        100000,
        "--capital",
        "-c",
        help="Initial capital (USD)",
    ),
    data_path: str = typer.Option(
        "./data",
        "--data-path",
        "-d",
        help="Path to Parquet data directory",
    ),
    earnings_dataset: str = typer.Option(
        "earnings",
        "--earnings-dataset",
        "-e",
        help="Dataset name for earnings calendar data",
    ),
    output_dir: str = typer.Option(
        "./backtest_results",
        "--output",
        "-o",
        help="Output directory for results",
    ),
):
    """
    Backtest earnings calendar spread strategies.

    Runs options backtests using historical data from Parquet files.
    Supports three strategy variants:
    - generic_calendar: Standard calendar spreads
    - pre_earnings: Timed around earnings announcements
    - iv_based: With strict IV term structure filtering

    Example:
        dlt-ibapi backtest-earnings-spreads \\
            --strategy iv_based \\
            --symbols AAPL MSFT GOOGL \\
            --start-date 2023-01-01 \\
            --end-date 2024-12-31 \\
            --capital 100000
    """
    try:
        console.print("\n[bold cyan]📊 Earnings Calendar Spread Backtest[/bold cyan]\n")

        # Import required modules
        console.print("Loading modules...", end=" ")
        try:
            from tools.strategies.options import (
                CalendarSpreadStrategy,
                CalendarSpreadConfig,
                PreEarningsCalendarSpreadStrategy,
                PreEarningsConfig,
                IVBasedCalendarSpreadStrategy,
                IVBasedConfig,
            )
            from dlt_ibapi.backtest import (
                IBBacktestDataProvider,
                EarningsCalendarProvider,
            )
            console.print("[green]✓[/green]")
        except ImportError as e:
            console.print(f"[red]✗[/red]\n[red]Error: {e}[/red]")
            console.print("\nMake sure 'tools' package is installed:")
            console.print("  cd ../tools && uv sync")
            raise typer.Exit(1)

        # Parse dates
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        # Initialize data providers
        console.print("Initializing data providers...", end=" ")
        data_provider = IBBacktestDataProvider(data_path)
        earnings_provider = EarningsCalendarProvider(data_path, earnings_dataset)
        console.print("[green]✓[/green]")

        # Create strategy configuration
        console.print(f"Configuring {strategy} strategy...", end=" ")

        if strategy == "generic_calendar":
            config = CalendarSpreadConfig(
                underlying_symbols=symbols,
                front_dte_range=(10, 20),
                back_dte_range=(30, 50),
                strike_selection="ATM",
                option_type="C",
                profit_target=0.30,
                stop_loss=-0.50,
            )
            strat = CalendarSpreadStrategy(config)

        elif strategy == "pre_earnings":
            config = PreEarningsConfig(
                underlying_symbols=symbols,
                entry_window=(10, 25),
                exit_buffer=2,
                front_dte_range=(14, 25),
                back_dte_range=(35, 60),
                option_type="C",
                profit_target=0.30,
            )
            strat = PreEarningsCalendarSpreadStrategy(config, earnings_provider)

        elif strategy == "iv_based":
            config = IVBasedConfig(
                underlying_symbols=symbols,
                entry_window=(10, 25),
                exit_buffer=2,
                iv_contango_min=0.05,
                iv_percentile_max=50.0,
                front_dte_range=(14, 25),
                back_dte_range=(35, 60),
                option_type="C",
            )
            strat = IVBasedCalendarSpreadStrategy(config, earnings_provider)

        else:
            console.print(f"[red]✗[/red]\n[red]Unknown strategy: {strategy}[/red]")
            console.print("Valid strategies: generic_calendar, pre_earnings, iv_based")
            raise typer.Exit(1)

        console.print("[green]✓[/green]")

        # Display configuration
        table = Table(title="Backtest Configuration")
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Strategy", strategy)
        table.add_row("Symbols", ", ".join(symbols))
        table.add_row("Start Date", start_date)
        table.add_row("End Date", end_date)
        table.add_row("Initial Capital", f"${initial_capital:,.0f}")
        table.add_row("Data Path", data_path)

        console.print(table)
        console.print()

        # Run backtest
        console.print("[bold]Running backtest...[/bold]")

        from dlt_ibapi.backtest import (
            OptionsBacktestRunner,
            OptionsChainProvider,
        )

        # Initialize option chain provider
        chain_provider = OptionsChainProvider(data_provider.option_chain_reader)

        # Create backtest runner with validation
        runner = OptionsBacktestRunner(
            strategy=strat,
            data_provider=data_provider,
            option_chain_provider=chain_provider,
            initial_capital=initial_capital,
            commission_per_contract=0.65,
            earnings_calendar_provider=earnings_provider,  # For pre-flight validation
        )

        # Run backtest with validation
        console.print("[dim]Running pre-flight validation...[/dim]")
        result = runner.run(
            start_date=start.date(),
            end_date=end.date(),
            validate_data=True,  # Validate data availability before backtest
        )

        # Display results
        console.print("\n[bold cyan]📈 Backtest Results[/bold cyan]\n")

        results_table = Table(title="Performance Summary")
        results_table.add_column("Metric", style="cyan")
        results_table.add_column("Value", style="green")

        summary = result.to_dict()
        results_table.add_row("Initial Capital", f"${summary['initial_capital']:,.0f}")
        results_table.add_row("Final Value", f"${summary['final_value']:,.0f}")
        results_table.add_row("Total Return", f"${summary['total_return']:,.2f}")
        results_table.add_row("Total Return %", f"{summary['total_return_pct']:.2f}%")
        results_table.add_row("", "")
        results_table.add_row("Number of Trades", str(summary['num_trades']))
        results_table.add_row("Winning Trades", str(summary['winning_trades']))
        results_table.add_row("Losing Trades", str(summary['losing_trades']))
        results_table.add_row("Win Rate", f"{summary['win_rate']:.1f}%")
        results_table.add_row("", "")
        results_table.add_row("Average Win", f"${summary['avg_win']:,.2f}")
        results_table.add_row("Average Loss", f"${summary['avg_loss']:,.2f}")
        results_table.add_row("Profit Factor", f"{summary['profit_factor']:.2f}")
        results_table.add_row("", "")
        results_table.add_row("Max Drawdown", f"${summary['max_drawdown']:,.2f}")
        results_table.add_row("Max Drawdown %", f"{summary['max_drawdown_pct']:.2f}%")

        console.print(results_table)

        # Export results
        console.print(f"\n[bold]Exporting results to {output_dir}...[/bold]")

        from pathlib import Path
        import json

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Export summary as JSON
        summary_file = output_path / f"summary_{strategy}_{start.date()}_{end.date()}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        console.print(f"  [green]✓[/green] Summary: {summary_file}")

        # Export equity curve as CSV
        equity_file = output_path / f"equity_curve_{strategy}_{start.date()}_{end.date()}.csv"
        result.equity_curve.write_csv(equity_file)
        console.print(f"  [green]✓[/green] Equity curve: {equity_file}")

        # Export trades as CSV
        if result.trades:
            import polars as pl
            trades_df = pl.DataFrame(result.trades)
            trades_file = output_path / f"trades_{strategy}_{start.date()}_{end.date()}.csv"
            trades_df.write_csv(trades_file)
            console.print(f"  [green]✓[/green] Trades: {trades_file}")

        # Create equity curve plot
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt

            plt.figure(figsize=(12, 6))
            timestamps = result.equity_curve['timestamp'].to_list()
            values = result.equity_curve['portfolio_value'].to_list()

            plt.plot(timestamps, values, linewidth=2, color='#2E86AB')
            plt.axhline(y=initial_capital, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
            plt.title(f'{strategy.replace("_", " ").title()} - Equity Curve', fontsize=14, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Portfolio Value ($)', fontsize=12)
            plt.grid(True, alpha=0.3)
            plt.legend()
            plt.tight_layout()

            plot_file = output_path / f"equity_curve_{strategy}_{start.date()}_{end.date()}.png"
            plt.savefig(plot_file, dpi=300, bbox_inches='tight')
            plt.close()

            console.print(f"  [green]✓[/green] Equity curve plot: {plot_file}")

        except ImportError:
            console.print("  [yellow]⚠[/yellow]  Skipping plot (matplotlib not installed)")
        except Exception as e:
            console.print(f"  [yellow]⚠[/yellow]  Plot generation failed: {e}")

        console.print(f"\n[green]✓ Backtest complete! Results saved to {output_dir}[/green]")

    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        import traceback
        console.print(traceback.format_exc())
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

        # Create pipeline
        pipeline = dlt.pipeline(
            pipeline_name=pipeline_name,
            destination=dlt.destinations.filesystem(bucket_url="data"),
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

            info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")

        if info.has_failed_jobs:
            console.print("[red]✗[/red] Load failed!")
            raise typer.Exit(1)

        console.print("[green]✓[/green] Earnings loaded successfully!\n")

        # Show summary
        from .repositories import EarningsCalendarReader
        reader = EarningsCalendarReader("./data", dataset)

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

    console.print(f"\n[bold cyan]Upcoming Earnings ({days_ahead} days)[/bold cyan]\n")

    try:
        reader = EarningsCalendarReader("./data", dataset)

        # Get upcoming earnings
        earnings = reader.get_upcoming_earnings(
            days_ahead=days_ahead,
            symbols=symbols,
            earnings_time=earnings_time,
        )

        if earnings.empty:
            console.print("[dim]No upcoming earnings found[/dim]")
            return

        # Display as table
        table = Table(title=f"Upcoming Earnings (Next {days_ahead} Days)")
        table.add_column("Symbol", style="cyan")
        table.add_column("Date", style="green")
        table.add_column("Time", style="yellow")
        table.add_column("Company", style="dim")
        table.add_column("EPS Forecast", justify="right")

        for _, row in earnings.iterrows():
            table.add_row(
                row["symbol"],
                str(row["earnings_date"]),
                row.get("earnings_time", "UNKNOWN"),
                row.get("company_name", "")[:30],  # Truncate long names
                f"${row['eps_forecast']:.2f}" if pd.notna(row.get("eps_forecast")) else "N/A",
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(earnings)} earnings event(s)[/dim]")

    except ValueError as e:
        if "does not exist" in str(e):
            console.print(f"[red]✗[/red] Earnings dataset not found: {dataset}")
            console.print(f"\n[yellow]Load earnings data first:[/yellow]")
            console.print(f"  dlt-ibapi load-earnings /path/to/earnings.json")
        else:
            console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
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
    database_path: Path = typer.Option(
        Path("data"),
        "--database-path",
        help="Path to data directory",
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
    Pre-populate contract cache by resolving symbols to IB contracts.

    This command resolves symbols to Interactive Brokers contract details and
    caches them for faster subsequent operations. Useful for:
    - Pre-resolving earnings symbols before snapshot/backfill
    - Validating symbols before expensive operations
    - Building contract cache for offline use

    Examples:
        # Resolve specific symbols
        dlt-ibapi resolve-contracts AAPL MSFT GOOGL

        # Resolve symbols from earnings calendar
        dlt-ibapi resolve-contracts --earnings-date 2025-11-13

        # Resolve from earnings JSON file
        dlt-ibapi resolve-contracts --earnings-file earnings.json

    The command will:
    - Skip symbols already in cache
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

        # Create params
        params = ResolveContractsParams(
            symbols=symbols,
            earnings_date=parsed_earnings_date,
            earnings_file=earnings_file,
            database_path=database_path,
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
def version():
    """Show dlt-ibapi version."""
    from . import __version__
    console.print(f"dlt-ibapi version: {__version__}")


def main():
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
