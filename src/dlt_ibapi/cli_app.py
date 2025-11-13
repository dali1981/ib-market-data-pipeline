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
    symbol: str = typer.Argument(..., help="Underlying symbol (e.g., AAPL)"),
    snapshot_date: Optional[str] = typer.Option(
        None, "--date", "-d", help="Snapshot date (YYYY-MM-DD, default: today)"
    ),
    min_dte: int = typer.Option(7, "--min-dte", help="Minimum days to expiration"),
    max_dte: int = typer.Option(365, "--max-dte", help="Maximum days to expiration"),
    pipeline_name: str = typer.Option(
        "ib_snapshots", "--pipeline-name", "--pipeline", help="Pipeline name"
    ),
    dataset: str = typer.Option("options", "--dataset", help="Dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --pipeline-name instead"),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
):
    """
    Capture option chain snapshot for a symbol.

    Example:
        dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
        dlt-ibapi snapshot AAPL --pipeline-name my_snapshots --dataset options
    """
    from .backfill import snapshot_option_chain
    from .repositories import OptionChainSnapshotReader

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use --pipeline-name instead.[/yellow]")
        pipeline_name = database.replace(".duckdb", "")

    console.print(f"\n[bold cyan]Capturing option chain snapshot for {symbol}[/bold cyan]\n")

    # Parse date
    snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date() if snapshot_date else date.today()

    console.print(f"Symbol:        {symbol}")
    console.print(f"Date:          {snap_date}")
    console.print(f"DTE range:     {min_dte} to {max_dte}")
    console.print(f"Pipeline:      {pipeline_name}")
    console.print(f"Dataset:       {dataset}\n")

    try:
        # Get connection config
        conn_config = get_connection_config(config_file)

        # Create pipeline with filesystem destination (Parquet)
        pipeline = dlt.pipeline(
            pipeline_name=pipeline_name,
            destination=dlt.destinations.filesystem(bucket_url="data"),
            dataset_name=dataset,
        )

        # Capture snapshot
        with console.status("[bold green]Capturing snapshot..."):
            data = snapshot_option_chain(
                underlying=symbol,
                snapshot_date=snap_date,
                connection_config=conn_config,
                min_dte=min_dte,
                max_dte=max_dte,
            )

            info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")

        if info.has_failed_jobs:
            console.print("[red]✗[/red] Snapshot capture failed!")
            raise typer.Exit(1)

        console.print("[green]✓[/green] Snapshot captured successfully!")

        # Query and display results (reader uses Parquet directory)
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
    dataset: str = typer.Option("options", "--dataset", help="Dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use --data-dir instead"),
):
    """
    List available option chain snapshots.

    Example:
        dlt-ibapi list-snapshots AAPL
        dlt-ibapi list-snapshots --data-dir ./data --dataset options
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
    dataset: str = typer.Option("options", "--dataset", help="Dataset name"),
    database: Optional[str] = typer.Option(None, "--database", "--db", help="[Deprecated] Use data_dir instead"),
):
    """
    Show Parquet data statistics (table sizes, date ranges, contract counts).

    Example:
        dlt-ibapi stats ./data --dataset stocks
        dlt-ibapi stats ./data --dataset options
    """
    import duckdb
    import glob

    # Handle legacy --database argument
    if database:
        console.print("[yellow]Warning: --database is deprecated. Use data_dir argument instead.[/yellow]")
        data_dir = database

    console.print(f"\n[bold cyan]Parquet Data Statistics[/bold cyan]\n")
    console.print(f"Data directory: {data_dir}")
    console.print(f"Dataset:        {dataset}\n")

    try:
        data_path = Path(data_dir) / dataset

        if not data_path.exists():
            console.print(f"[red]✗[/red] Data directory does not exist: {data_path}")
            raise typer.Exit(1)

        # Find all table directories (subdirectories with Parquet files)
        table_dirs = [d for d in data_path.iterdir() if d.is_dir()]

        if not table_dirs:
            console.print(f"No tables found in dataset '{dataset}'")
            return

        conn = duckdb.connect(":memory:")

        for table_dir in sorted(table_dirs):
            table_name = table_dir.name
            parquet_pattern = f"{table_dir}/**/*.parquet"

            # Check if any Parquet files exist
            parquet_files = glob.glob(parquet_pattern, recursive=True)
            if not parquet_files:
                console.print(f"[dim]{table_name}[/dim]")
                console.print(f"  [dim]No Parquet files found[/dim]\n")
                continue

            # Get row count
            count_df = conn.execute(f"""
                SELECT COUNT(*) as count
                FROM parquet_scan('{table_dir}/**/*.parquet', hive_partitioning=true)
            """).df()
            row_count = int(count_df.iloc[0]['count'])

            # Get date range if table has time column
            try:
                date_range_df = conn.execute(f"""
                    SELECT
                        MIN(DATE(time)) as min_date,
                        MAX(DATE(time)) as max_date
                    FROM parquet_scan('{table_dir}/**/*.parquet', hive_partitioning=true)
                """).df()

                if not date_range_df.empty and not date_range_df.iloc[0].isnull().all():
                    min_date = date_range_df.iloc[0]['min_date']
                    max_date = date_range_df.iloc[0]['max_date']
                    date_info = f"{min_date} to {max_date}"
                else:
                    date_info = "N/A"
            except:
                date_info = "N/A"

            console.print(f"[green]{table_name}[/green]")
            console.print(f"  Rows: {row_count:,}")
            console.print(f"  Date range: {date_info}\n")

        conn.close()

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
    earnings_path: str = typer.Option(
        "./data/earnings_calendar",
        "--earnings-path",
        "-e",
        help="Path to earnings calendar data",
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
        earnings_provider = EarningsCalendarProvider(earnings_path)
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

        # TODO: Implement full backtest execution
        # For now, show that configuration is working

        console.print("[yellow]⚠️  Note:[/yellow] Full backtest execution coming soon!")
        console.print("Next steps:")
        console.print("1. Implement backtest engine integration")
        console.print("2. Add results export (equity curve, trades, metrics)")
        console.print("3. Add performance visualization")

        console.print("\n[green]✓ Configuration validated successfully[/green]")

    except Exception as e:
        console.print(f"\n[red bold]✗ Error:[/red bold] {str(e)}")
        import traceback
        console.print(traceback.format_exc())
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
