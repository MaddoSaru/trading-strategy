"""
Paper trading poller: check combined signals and execute paper trades.

Usage:
    uv run python -m paper_trading --assets nasdaq,sp500 --interval 1d
    uv run python -m paper_trading --dry-run
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from rich.console import Console
from rich.table import Table

from etl.fetcher import ASSETS, fetch
from etl.storage import load, save
from indicators.technical import add_indicators
from paper_trading.engine import PaperTradingEngine
from paper_trading.signals import get_combined_signal

console = Console()


def _get_current_price(symbol: str, interval: str, period: str) -> float:
    df = load(symbol, interval)
    if df is None:
        df = fetch(symbol, interval=interval, period=period)
        save(df, symbol, interval)
    return float(add_indicators(df).iloc[-1]["close"])


def _build_source_label(tv_rec: str, strategies: dict[str, str], action: str) -> str:
    active = [k for k, v in strategies.items() if v == action]
    return f"poll|tv:{tv_rec}|strategies:{','.join(active) or 'none'}"


@click.command()
@click.option("--assets", default="nasdaq,sp500", show_default=True,
              help="Comma-separated list of assets to poll")
@click.option("--interval", default="1d", show_default=True,
              help="Candle interval (1d, 4h, 1h, etc.)")
@click.option("--period", default="2y", show_default=True,
              help="Data lookback period for strategy signals")
@click.option("--capital", default=10_000.0, show_default=True,
              help="Initial capital (only applied on first run)")
@click.option("--buy-threshold", default=3, show_default=True,
              help="Minimum BUY votes (out of 6) required to execute a BUY")
@click.option("--sell-threshold", default=2, show_default=True,
              help="Minimum SELL votes (out of 6) required to execute a SELL")
@click.option("--dry-run", is_flag=True,
              help="Print signals without executing any trades")
def poll(assets, interval, period, capital, buy_threshold, sell_threshold, dry_run):
    """Check combined TradingView + strategy signals and execute paper trades."""
    asset_list = [a.strip() for a in assets.split(",")]
    engine = PaperTradingEngine(initial_capital=capital)

    console.rule("[bold blue]Paper Trading Poll")

    for asset in asset_list:
        symbol = ASSETS.get(asset, asset.upper())
        console.print(f"\n[bold cyan]{asset.upper()} ({symbol})[/bold cyan]")

        result = get_combined_signal(asset, interval, period, buy_threshold, sell_threshold)
        action = result["action"]
        tv = result["breakdown"]["tradingview"]
        strategies = result["breakdown"]["strategies"]

        table = Table(show_header=True, header_style="bold")
        table.add_column("Source", style="dim")
        table.add_column("Signal")
        table.add_column("BUY", justify="right")
        table.add_column("SELL", justify="right")

        table.add_row(
            "TradingView", tv["recommendation"],
            str(tv["buy_votes"]), str(tv["sell_votes"]),
        )
        for strat, sig in strategies.items():
            b = "1" if sig == "BUY" else "0"
            s = "1" if sig == "SELL" else "0"
            table.add_row(strat, sig, b, s)

        color = "green" if action == "BUY" else ("red" if action == "SELL" else "yellow")
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold {color}]{action}[/bold {color}]",
            f"[bold]{result['buy_votes']}[/bold]",
            f"[bold]{result['sell_votes']}[/bold]",
        )
        console.print(table)

        if dry_run:
            console.print(f"[yellow]DRY RUN — no trade executed[/yellow]")
            continue

        price = _get_current_price(symbol, interval, period)
        source = _build_source_label(tv["recommendation"], strategies, action)

        if action == "BUY":
            order = engine.execute_order(symbol, asset, "BUY", price, signal_source=source)
            if "error" in order:
                console.print(f"[yellow]BUY skipped: {order['error']}[/yellow]")
            else:
                console.print(
                    f"[green]BUY {order['shares']:.4f} {symbol} @ ${price:.2f} "
                    f"(invested ${order['cash_invested']:.2f})[/green]"
                )
        elif action == "SELL":
            order = engine.execute_order(symbol, asset, "SELL", price, signal_source=source)
            if "error" in order:
                console.print(f"[yellow]SELL skipped: {order['error']}[/yellow]")
            else:
                pnl_color = "green" if order["pnl"] >= 0 else "red"
                console.print(
                    f"[red]SELL {order['shares']:.4f} {symbol} @ ${price:.2f}[/red] | "
                    f"P&L: [{pnl_color}]${order['pnl']:.2f} ({order['pnl_pct']:.2f}%)[/{pnl_color}]"
                )
        else:
            console.print(
                f"[dim]HOLD — votes: {result['buy_votes']} buy / {result['sell_votes']} sell "
                f"(thresholds: {buy_threshold}/{sell_threshold})[/dim]"
            )

    console.rule()
