from dataclasses import dataclass, field

import click
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

from etl.fetcher import ASSETS, fetch
from etl.storage import load, save
from indicators.technical import add_indicators
from strategies import REGISTRY
from strategies.base import Signal, Strategy

console = Console()


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: float

    @property
    def pnl(self) -> float:
        return self.shares * (self.exit_price - self.entry_price)

    @property
    def return_pct(self) -> float:
        return (self.exit_price / self.entry_price) - 1


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    initial_capital: float = 10_000.0

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) else self.initial_capital

    @property
    def total_return(self) -> float:
        return (self.final_equity / self.initial_capital) - 1

    @property
    def sharpe_ratio(self) -> float:
        returns = self.equity_curve.pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        return float((returns.mean() / returns.std()) * np.sqrt(252))

    @property
    def max_drawdown(self) -> float:
        rolling_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - rolling_max) / rolling_max
        return float(drawdown.min())

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl > 0) / len(self.trades)

    def summary(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "win_rate_pct": round(self.win_rate * 100, 2),
            "num_trades": len(self.trades),
        }


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    initial_capital: float = 10_000.0,
    commission: float = 0.001,
) -> BacktestResult:
    signals = strategy.generate_signals(df)

    position: float = 0.0
    cash: float = initial_capital
    entry_price: float = 0.0
    entry_date: pd.Timestamp | None = None
    trades: list[Trade] = []
    equity: list[float] = []

    for date, row in df.iterrows():
        price = float(row["close"])
        sig = signals.loc[date]

        if sig == Signal.BUY and position == 0.0:
            shares = (cash * (1 - commission)) / price
            position = shares
            entry_price = price
            entry_date = date
            cash = 0.0

        elif sig == Signal.SELL and position > 0.0:
            exit_price = price * (1 - commission)
            trades.append(Trade(entry_date, date, entry_price, exit_price, position))
            cash = position * exit_price
            position = 0.0

        equity.append(cash + position * price)

    # Force-close any open position at last bar
    if position > 0.0:
        last_price = float(df["close"].iloc[-1]) * (1 - commission)
        trades.append(Trade(entry_date, df.index[-1], entry_price, last_price, position))
        equity[-1] = position * last_price

    return BacktestResult(
        trades=trades,
        equity_curve=pd.Series(equity, index=df.index),
        initial_capital=initial_capital,
    )


@click.command()
@click.option("--strategy", "-s", "strategy_name", required=True,
              type=click.Choice(list(REGISTRY.keys())), help="Strategy to backtest")
@click.option("--asset", "-a", default="nasdaq", type=click.Choice(list(ASSETS.keys())))
@click.option("--interval", "-i", default="1d")
@click.option("--period", "-p", default="5y")
@click.option("--capital", "-c", default=10_000.0, type=float)
def cli(strategy_name, asset, interval, period, capital):
    """Run a backtest and print performance summary."""
    symbol = ASSETS[asset]

    df = load(symbol, interval)
    if df is None:
        console.print(f"[yellow]No cached data — fetching {symbol} [{interval}]...[/yellow]")
        df = fetch(symbol, interval=interval, period=period)
        save(df, symbol, interval)

    df = add_indicators(df)
    strategy = REGISTRY[strategy_name]()
    result = run_backtest(df, strategy, initial_capital=capital)

    table = Table(title=f"{strategy_name} on {symbol} [{interval}] — {period}")
    for k, v in result.summary().items():
        table.add_row(k, str(v))

    console.print(table)

    if result.trades:
        console.print(f"\n[bold]Last 5 trades:[/bold]")
        trade_table = Table()
        trade_table.add_column("Entry")
        trade_table.add_column("Exit")
        trade_table.add_column("Entry $")
        trade_table.add_column("Exit $")
        trade_table.add_column("PnL $")
        trade_table.add_column("Return %")
        for t in result.trades[-5:]:
            color = "green" if t.pnl > 0 else "red"
            trade_table.add_row(
                str(t.entry_date.date()),
                str(t.exit_date.date()),
                f"{t.entry_price:.2f}",
                f"{t.exit_price:.2f}",
                f"[{color}]{t.pnl:.2f}[/{color}]",
                f"[{color}]{t.return_pct * 100:.2f}%[/{color}]",
            )
        console.print(trade_table)


if __name__ == "__main__":
    cli()
