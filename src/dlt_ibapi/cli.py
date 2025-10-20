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
            contract = make_stock("AAPL", "SMART", "USD")
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
def version():
    """Show dlt-ibapi version."""
    from . import __version__
    console.print(f"dlt-ibapi version: {__version__}")


def main():
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
