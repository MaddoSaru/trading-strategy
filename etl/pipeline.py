import click
from rich.console import Console
from rich.table import Table

from etl.fetcher import ASSETS, fetch
from etl.storage import STORAGE_BACKEND, save

console = Console()

DEFAULT_INTERVALS = ["1d", "1wk", "1h", "15m", "5m"]
DEFAULT_PERIOD = "2y"

# Intervals that support arbitrary date ranges via start/end.
# Intraday intervals have hard yfinance limits (1h=730d, 15m/5m=60d, 1m=7d)
# and are always fetched with their max period instead.
_DATE_RANGE_INTERVALS = {"1d", "5d", "1wk", "1mo", "3mo"}


def run_etl(
    assets: list[str] = list(ASSETS.keys())[:2],
    intervals: list[str] = DEFAULT_INTERVALS,
    period: str = DEFAULT_PERIOD,
    start: str | None = None,
    end: str | None = None,
) -> None:
    console.print(f"[dim]Storage backend: [bold]{STORAGE_BACKEND}[/bold][/dim]")

    if STORAGE_BACKEND == "mysql":
        from etl.db import drop_legacy_table
        drop_legacy_table()

    table = Table(title="ETL Results")
    table.add_column("Asset")
    table.add_column("Symbol")
    table.add_column("Interval")
    table.add_column("Rows")
    table.add_column("Start")
    table.add_column("End")
    table.add_column("Status")

    for asset in assets:
        symbol = ASSETS.get(asset, asset.upper())
        for interval in intervals:
            try:
                use_date_range = start and interval in _DATE_RANGE_INTERVALS
                with console.status(f"Fetching {symbol} [{interval}]..."):
                    if use_date_range:
                        df = fetch(symbol, interval=interval, start=start, end=end)
                    else:
                        df = fetch(symbol, interval=interval, period=period)

                if df.empty:
                    raise ValueError("no data returned (yfinance limit for this interval)")

                with console.status(f"Saving {symbol} [{interval}] → {STORAGE_BACKEND}..."):
                    save(df, symbol, interval)

                table.add_row(
                    asset, symbol, interval,
                    str(len(df)),
                    str(df.index[0].date()),
                    str(df.index[-1].date()),
                    "[green]✓ saved[/green]",
                )
            except Exception as e:
                table.add_row(asset, symbol, interval, "-", "-", "-", f"[red]✗ {e}[/red]")

    console.print(table)


@click.command()
@click.option("--assets", "-a", multiple=True, default=["nasdaq", "sp500"], show_default=True)
@click.option("--intervals", "-i", multiple=True, default=DEFAULT_INTERVALS, show_default=True)
@click.option("--period", "-p", default=DEFAULT_PERIOD, show_default=True,
              help="Period for intraday intervals (ignored when --start is set for daily/weekly).")
@click.option("--start", default=None, help="Start date YYYY-MM-DD (applied to 1d/1wk only).")
@click.option("--end", default=None, help="End date YYYY-MM-DD (defaults to today).")
def cli(assets, intervals, period, start, end):
    """Fetch historical OHLCV data and persist to MySQL (or parquet if STORAGE_BACKEND=parquet)."""
    run_etl(list(assets), list(intervals), period, start, end)


if __name__ == "__main__":
    cli()
