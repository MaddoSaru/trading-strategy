"""
FastMCP server exposing trading strategy tools to Claude.

Tools:
- get_tv_analysis       — TradingView recommendation + indicators for any symbol
- fetch_historical_data — Download & cache OHLCV via yfinance
- get_current_signals   — Run all strategies on latest data, return signals
- backtest_strategy     — Backtest a single strategy, return performance metrics
- compare_strategies    — Compare all strategies on same asset/interval
- list_strategies       — List available strategies and their parameters
"""

import sys
from pathlib import Path

# Allow running as `python -m mcp_server.server` from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from fastmcp import FastMCP

from etl.fetcher import ASSETS, fetch
from etl.storage import load, save
from indicators.technical import add_indicators
from strategies import REGISTRY
from strategies.base import Signal

mcp = FastMCP("trading-strategy")

# TradingView exchange mapping for common ETFs/indices
_TV_EXCHANGES = {
    "QQQ": ("NASDAQ", "america"),
    "SPY": ("AMEX", "america"),
    "^NDX": ("NASDAQ", "america"),
    "^GSPC": ("SP:SPX", "america"),
    "AAPL": ("NASDAQ", "america"),
    "TSLA": ("NASDAQ", "america"),
    "NVDA": ("NASDAQ", "america"),
}

_TV_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1D",
    "1wk": "1W",
    "1mo": "1M",
}


def _load_or_fetch(symbol: str, interval: str, period: str, refresh: bool) -> pd.DataFrame:
    df = None if refresh else load(symbol, interval)
    if df is None:
        df = fetch(symbol, interval=interval, period=period)
        save(df, symbol, interval)
    return add_indicators(df)


@mcp.tool()
def get_tv_analysis(
    symbol: str = "QQQ",
    exchange: str = "NASDAQ",
    screener: str = "america",
    interval: str = "1d",
) -> dict:
    """
    Get TradingView technical analysis recommendation for any symbol.

    Common exchange values: NASDAQ (QQQ, AAPL), AMEX (SPY), NYSE (stock),
    BINANCE (crypto). Screener is usually "america" for US equities.
    Interval: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1wk, 1mo.
    """
    try:
        from tradingview_ta import TA_Handler, Interval as TVInterval

        tv_interval_map = {
            "1m": TVInterval.INTERVAL_1_MINUTE,
            "5m": TVInterval.INTERVAL_5_MINUTES,
            "15m": TVInterval.INTERVAL_15_MINUTES,
            "30m": TVInterval.INTERVAL_30_MINUTES,
            "1h": TVInterval.INTERVAL_1_HOUR,
            "2h": TVInterval.INTERVAL_2_HOURS,
            "4h": TVInterval.INTERVAL_4_HOURS,
            "1d": TVInterval.INTERVAL_1_DAY,
            "1wk": TVInterval.INTERVAL_1_WEEK,
            "1mo": TVInterval.INTERVAL_1_MONTH,
        }

        handler = TA_Handler(
            symbol=symbol.upper(),
            screener=screener,
            exchange=exchange,
            interval=tv_interval_map.get(interval, TVInterval.INTERVAL_1_DAY),
        )
        a = handler.get_analysis()

        return {
            "symbol": symbol.upper(),
            "exchange": exchange,
            "interval": interval,
            "recommendation": a.summary["RECOMMENDATION"],
            "buy_signals": a.summary["BUY"],
            "sell_signals": a.summary["SELL"],
            "neutral_signals": a.summary["NEUTRAL"],
            "indicators": {
                "close": a.indicators.get("close"),
                "rsi": a.indicators.get("RSI"),
                "rsi_14": a.indicators.get("RSI[1]"),
                "macd": a.indicators.get("MACD.macd"),
                "macd_signal": a.indicators.get("MACD.signal"),
                "sma_20": a.indicators.get("SMA20"),
                "sma_50": a.indicators.get("SMA50"),
                "sma_200": a.indicators.get("SMA200"),
                "ema_20": a.indicators.get("EMA20"),
                "bb_upper": a.indicators.get("BB.upper"),
                "bb_lower": a.indicators.get("BB.lower"),
                "adx": a.indicators.get("ADX"),
                "stoch_k": a.indicators.get("Stoch.K"),
                "stoch_d": a.indicators.get("Stoch.D"),
                "atr": a.indicators.get("ATR"),
                "volume": a.indicators.get("volume"),
            },
            "oscillators": a.oscillators,
            "moving_averages": a.moving_averages,
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol, "interval": interval}


@mcp.tool()
def fetch_historical_data(
    asset: str = "nasdaq",
    interval: str = "1d",
    period: str = "2y",
    refresh: bool = False,
) -> dict:
    """
    Fetch and cache historical OHLCV data with technical indicators pre-computed.

    asset: "nasdaq" (QQQ) or "sp500" (SPY) — or any yfinance symbol.
    interval: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1wk, 1mo.
    period: 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max.
    refresh: Force re-download even if cached locally.
    """
    try:
        symbol = ASSETS.get(asset, asset.upper())
        df = _load_or_fetch(symbol, interval, period, refresh)

        latest = df.tail(5).reset_index()
        latest["datetime"] = latest["datetime"].astype(str)

        return {
            "symbol": symbol,
            "interval": interval,
            "total_rows": len(df),
            "start": str(df.index[0]),
            "end": str(df.index[-1]),
            "columns": list(df.columns),
            "latest_5_bars": latest.to_dict(orient="records"),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_current_signals(
    asset: str = "nasdaq",
    interval: str = "1d",
    period: str = "2y",
) -> dict:
    """
    Run all available strategies on the latest data and return their current signal (BUY/SELL/HOLD).
    Also returns key indicator values for context.
    """
    try:
        symbol = ASSETS.get(asset, asset.upper())
        df = _load_or_fetch(symbol, interval, period, refresh=False)
        latest = df.iloc[-1]

        signals: dict[str, str] = {}
        for name, cls in REGISTRY.items():
            strategy = cls()
            series = strategy.generate_signals(df)
            signals[name] = series.iloc[-1].name  # "BUY", "SELL", or "HOLD"

        def _safe(val) -> float | None:
            try:
                v = float(val)
                return None if pd.isna(v) else round(v, 4)
            except Exception:
                return None

        return {
            "symbol": symbol,
            "interval": interval,
            "as_of": str(df.index[-1]),
            "close": _safe(latest["close"]),
            "signals": signals,
            "indicators": {
                "rsi": _safe(latest.get("rsi")),
                "macd": _safe(latest.get("macd")),
                "macd_signal": _safe(latest.get("macd_signal")),
                "macd_hist": _safe(latest.get("macd_hist")),
                "sma_50": _safe(latest.get("sma_50")),
                "sma_200": _safe(latest.get("sma_200")),
                "ema_9": _safe(latest.get("ema_9")),
                "ema_21": _safe(latest.get("ema_21")),
                "bb_upper": _safe(latest.get("bb_upper")),
                "bb_mid": _safe(latest.get("bb_mid")),
                "bb_lower": _safe(latest.get("bb_lower")),
                "atr": _safe(latest.get("atr")),
                "stoch_k": _safe(latest.get("stoch_k")),
                "stoch_d": _safe(latest.get("stoch_d")),
                "vol_ratio": _safe(latest.get("vol_ratio")),
            },
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def backtest_strategy(
    strategy_name: str = "sma_crossover",
    asset: str = "nasdaq",
    interval: str = "1d",
    period: str = "5y",
    initial_capital: float = 10_000.0,
    strategy_params: dict | None = None,
) -> dict:
    """
    Backtest a strategy on historical data and return performance metrics + trade log.

    strategy_name: one of sma_crossover, rsi_macd, bollinger_band, ema_trend.
    strategy_params: optional dict of constructor kwargs (e.g. {"fast": 20, "slow": 100}).
    Returns: total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate_pct, num_trades, trades.
    """
    try:
        from backtest.engine import run_backtest

        if strategy_name not in REGISTRY:
            return {"error": f"Unknown strategy '{strategy_name}'. Available: {list(REGISTRY.keys())}"}

        symbol = ASSETS.get(asset, asset.upper())
        df = _load_or_fetch(symbol, interval, period, refresh=False)

        strategy = REGISTRY[strategy_name](**(strategy_params or {}))
        result = run_backtest(df, strategy, initial_capital=initial_capital)
        summary = result.summary()

        trades = [
            {
                "entry_date": str(t.entry_date.date()),
                "exit_date": str(t.exit_date.date()),
                "entry_price": round(t.entry_price, 2),
                "exit_price": round(t.exit_price, 2),
                "pnl": round(t.pnl, 2),
                "return_pct": round(t.return_pct * 100, 2),
            }
            for t in result.trades
        ]

        return {
            "strategy": strategy_name,
            "params": strategy_params or {},
            "symbol": symbol,
            "interval": interval,
            "period": period,
            **summary,
            "last_10_trades": trades[-10:],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def compare_strategies(
    asset: str = "nasdaq",
    interval: str = "1d",
    period: str = "5y",
    initial_capital: float = 10_000.0,
) -> dict:
    """
    Run all strategies on the same asset/interval and return a side-by-side comparison
    sorted by total return. Useful for picking the best strategy for a given market/timeframe.
    """
    try:
        from backtest.engine import run_backtest

        symbol = ASSETS.get(asset, asset.upper())
        df = _load_or_fetch(symbol, interval, period, refresh=False)

        results = {}
        for name, cls in REGISTRY.items():
            strategy = cls()
            result = run_backtest(df, strategy, initial_capital=initial_capital)
            results[name] = result.summary()

        sorted_results = dict(
            sorted(results.items(), key=lambda x: x[1]["total_return_pct"], reverse=True)
        )

        return {
            "symbol": symbol,
            "interval": interval,
            "period": period,
            "ranked_strategies": sorted_results,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_strategies() -> dict:
    """List all available strategies, their parameters and default values."""
    import inspect

    strategies = {}
    for name, cls in REGISTRY.items():
        sig = inspect.signature(cls.__init__)
        params = {
            k: v.default if v.default is not inspect.Parameter.empty else "required"
            for k, v in sig.parameters.items()
            if k != "self"
        }
        strategies[name] = {
            "class": cls.__name__,
            "description": (cls.__doc__ or "").strip(),
            "parameters": params,
        }

    return {"strategies": strategies, "assets": ASSETS}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
