# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ETL + strategy engine for trading Nasdaq (QQQ) and S&P 500 (SPY). It fetches historical OHLCV data via yfinance, computes technical indicators, generates buy/sell signals from pluggable strategies, runs backtests, and exposes everything as an MCP server so Claude can reason about the markets directly.

## Setup

```bash
cd ~/Desktop/personal/git/trading-strategy
uv sync                 # Install all dependencies
```

### MySQL setup

The ETL process writes to a local MySQL database (default name: `trading_strategy`).
Set these in `~/.zshrc` (the database is auto-created on first run):

```bash
export MYSQL_HOST=localhost      # default
export MYSQL_PORT=3306           # default
export MYSQL_USER=root
export MYSQL_PASSWORD=your_password
export MYSQL_DB=trading_strategy # default
```

To fall back to local parquet files instead:
```bash
export STORAGE_BACKEND=parquet
```

### MCP server MySQL env vars

The MCP server is a subprocess — env vars must be passed at registration time:

```bash
claude mcp remove trading-strategy 2>/dev/null; \
claude mcp add --scope user trading-strategy \
  -e "MYSQL_USER=$MYSQL_USER" \
  -e "MYSQL_PASSWORD=$MYSQL_PASSWORD" \
  -e "MYSQL_HOST=${MYSQL_HOST:-localhost}" \
  -e "MYSQL_DB=${MYSQL_DB:-trading_strategy}" \
  -- ~/.local/bin/uv --directory ~/Desktop/personal/git/trading-strategy \
     run python -m mcp_server.server
```

## Common commands

```bash
# Fetch and store both assets, common timeframes → MySQL
uv run python -m etl.pipeline

# Fetch specific asset / interval / period
uv run python -m etl.pipeline --assets nasdaq --intervals 1h --period 5y

# Backtest a strategy
uv run python -m backtest.engine --strategy sma_crossover --asset nasdaq --interval 1d --period 5y
uv run python -m backtest.engine --strategy rsi_macd --asset sp500 --interval 4h --capital 50000

# Start the MCP server (stdio — used by Claude Code)
uv run python -m mcp_server.server
```

Available strategies: `sma_crossover`, `rsi_macd`, `bollinger_band`, `ema_trend`  
Available assets: `nasdaq` (QQQ), `sp500` (SPY), `nasdaq_index` (^NDX), `sp500_index` (^GSPC)  
Available intervals: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1wk`, `1mo`

## Registering the MCP server with Claude Code

See MySQL setup section above — credentials must be passed as `-e` flags at add time.

Once connected, Claude has access to these tools:
- `get_tv_analysis` — TradingView recommendation + 15+ indicators for any symbol/timeframe
- `fetch_historical_data` — Download & cache OHLCV with indicators pre-computed
- `get_current_signals` — All strategies' current BUY/SELL/HOLD signal on any asset
- `backtest_strategy` — Full backtest with Sharpe, drawdown, win rate, trade log
- `compare_strategies` — Side-by-side comparison of all strategies, ranked by return
- `list_strategies` — Enumerate strategies and their tunable parameters

## Architecture

```
etl/
  fetcher.py      ASSETS dict, fetch() wraps yfinance, resample_ohlcv() for synthetic 4h/2h
  db.py           MySQL engine singleton, create_tables(), upsert(), query() via SQLAlchemy
  storage.py      Unified save()/load() — routes to MySQL (default) or parquet (STORAGE_BACKEND=parquet)
  pipeline.py     CLI to bulk-fetch all assets × intervals and persist to storage backend

indicators/
  technical.py    Pure-pandas implementations: sma, ema, rsi, macd, bollinger_bands,
                  atr, stochastic, add_indicators() (adds all columns to a df copy)

strategies/
  base.py         Signal enum (BUY/SELL/HOLD), abstract Strategy with generate_signals()
  __init__.py     REGISTRY dict — the single source of truth for available strategies
  sma_crossover   Golden/death cross on configurable fast/slow SMAs
  rsi_macd        MACD crossover filtered by RSI oversold/overbought thresholds
  bollinger_band  Mean-reversion on Bollinger Band touches
  ema_trend       EMA 9/21 crossover with RSI direction filter

backtest/
  engine.py       run_backtest() → BacktestResult with trade list + equity curve;
                  Sharpe/drawdown/win-rate are computed as properties; CLI via click

mcp_server/
  server.py       FastMCP server; each tool calls into etl/strategies/backtest internally;
                  __main__.py lets it run as `python -m mcp_server`

data/             Parquet fallback cache (only used when STORAGE_BACKEND=parquet)
notebooks/        Jupyter exploration notebooks (not tracked)
```

### Key design decisions

- **No TA library dependency**: all indicators are implemented directly in `indicators/technical.py` using pandas/numpy to avoid `pandas-ta` / `ta-lib` compatibility issues.
- **yfinance doesn't support 4h**: `fetcher.py` fetches 1h and resamples when `interval="4h"` or `"2h"`.
- **fastmcp pinned `<2.14`**: versions ≥2.14 introduced a `docket` dependency that breaks on `fakeredis>=2.26`. See global CLAUDE.md for the patch script.
- **MySQL schema**: single `ohlcv` table with composite primary key `(symbol, interval, datetime)`. `etl/db.py:upsert()` uses `INSERT ... ON DUPLICATE KEY UPDATE` so re-running the ETL is idempotent.
- **Strategies are stateless**: `generate_signals(df)` always operates on the full dataframe and returns a full Series — no hidden state between calls.

## Adding a new strategy

1. Create `strategies/my_strategy.py` inheriting `Strategy`, implement `generate_signals()`.
2. Add it to `REGISTRY` in `strategies/__init__.py`.
3. It's immediately available in the backtest CLI and all MCP tools — no other changes needed.

## TradingView exchange reference

| Symbol | exchange param | screener |
|--------|---------------|----------|
| QQQ    | NASDAQ        | america  |
| SPY    | AMEX          | america  |
| ^NDX   | NASDAQ        | america  |
| AAPL   | NASDAQ        | america  |
| BTC    | BINANCE       | crypto   |
