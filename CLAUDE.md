# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ETL + strategy engine for trading Nasdaq (QQQ) and S&P 500 (SPY). It fetches historical OHLCV data via yfinance, computes technical indicators, generates buy/sell signals from pluggable strategies, runs backtests, and exposes everything as an MCP server so Claude can reason about the markets directly.

It also includes a paper trading engine that polls TradingView + strategy signals, executes simulated trades, and self-optimizes strategy parameters after every N closed positions.

## Setup

```bash
uv sync                 # Install all dependencies
```

### MySQL setup

The ETL process writes to a local MySQL database (default name: `trading_strategy`).
Set these environment variables (the database is auto-created on first run):

```bash
export MYSQL_HOST=localhost      # default
export MYSQL_PORT=3306           # default
export MYSQL_USER=your_user
export MYSQL_PASSWORD=your_password
export MYSQL_DB=trading_strategy # default
```

To fall back to local parquet files instead:
```bash
export STORAGE_BACKEND=parquet
```

### MCP server registration

The MCP server runs as a subprocess — env vars must be passed at registration time:

```bash
claude mcp remove trading-strategy 2>/dev/null; \
claude mcp add --scope user trading-strategy \
  -e "MYSQL_USER=$MYSQL_USER" \
  -e "MYSQL_PASSWORD=$MYSQL_PASSWORD" \
  -e "MYSQL_HOST=${MYSQL_HOST:-localhost}" \
  -e "MYSQL_DB=${MYSQL_DB:-trading_strategy}" \
  -- uv --directory /path/to/trading-strategy \
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

# Paper trading — dry-run (no trades executed)
uv run python -m paper_trading --dry-run

# Paper trading — live poll (executes trades when thresholds are met)
uv run python -m paper_trading --assets nasdaq,sp500 --interval 1d

# Start the MCP server (stdio — used by Claude Code)
uv run python -m mcp_server.server
```

Available strategies: `sma_crossover`, `rsi_macd`, `bollinger_band`, `ema_trend`  
Available assets: `nasdaq` (QQQ), `sp500` (SPY), `nasdaq_index` (^NDX), `sp500_index` (^GSPC)  
Available intervals: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1wk`, `1mo`

## MCP tools

Once the server is connected, Claude has access to these tools:

**Market data & analysis**
- `get_tv_analysis` — TradingView recommendation + 15+ indicators for any symbol/timeframe
- `fetch_historical_data` — Download & cache OHLCV with indicators pre-computed
- `get_current_signals` — All strategies' current BUY/SELL/HOLD signal on any asset
- `backtest_strategy` — Full backtest with Sharpe, drawdown, win rate, trade log
- `compare_strategies` — Side-by-side comparison of all strategies, ranked by return
- `list_strategies` — Enumerate strategies and their tunable parameters

**Paper trading**
- `get_paper_portfolio` — Portfolio snapshot: cash, open positions, unrealized/realized P&L
- `get_paper_trades` — Trade log (most recent first)
- `execute_paper_order` — Manually execute a paper BUY or SELL at current price
- `run_paper_poll` — Check combined signals and execute paper trades if thresholds are met
- `reset_paper_portfolio` — Wipe all paper trading data and start fresh

**Strategy optimization**
- `get_strategy_params` — Show active params per strategy (optimized vs defaults) + performance
- `optimize_strategies` — Manually trigger a full parameter grid search

## Architecture

```
etl/
  fetcher.py        ASSETS dict, fetch() wraps yfinance, resample_ohlcv() for synthetic 4h/2h
  db.py             MySQL engine singleton, create_tables(), upsert(), query() via SQLAlchemy
  storage.py        Unified save()/load() — routes to MySQL (default) or parquet (STORAGE_BACKEND=parquet)
  pipeline.py       CLI to bulk-fetch all assets × intervals and persist to storage backend

indicators/
  technical.py      Pure-pandas: sma, ema, rsi, macd, bollinger_bands, atr, stochastic,
                    add_indicators() (adds all columns to a df copy)

strategies/
  base.py           Signal enum (BUY/SELL/HOLD), abstract Strategy with generate_signals()
  __init__.py       REGISTRY dict — single source of truth for available strategies
  sma_crossover     Golden/death cross on configurable fast/slow SMAs
  rsi_macd          MACD crossover filtered by RSI oversold/overbought thresholds
  bollinger_band    Mean-reversion on Bollinger Band touches
  ema_trend         EMA crossover with RSI trend filter

backtest/
  engine.py         run_backtest() → BacktestResult with trade list + equity curve;
                    Sharpe/drawdown/win-rate computed as properties; CLI via click

paper_trading/
  models.py         MySQL DDL + raw SQL helpers for paper_portfolio, paper_positions,
                    paper_trades, paper_strategy_params tables
  engine.py         PaperTradingEngine — execute_order(), get_portfolio_snapshot(),
                    auto-triggers optimize_all() after every N SELL trades
  signals.py        get_combined_signal() — always fetches fresh data, runs TV + all
                    strategies with optimized params, returns vote-based BUY/SELL/HOLD
  optimizer.py      Grid-search over PARAM_GRIDS, ranks by Sharpe, persists best params
                    to paper_strategy_params; ~0.8s for 54 combos on 1y daily data
  poller.py         CLI entrypoint; prints signal table per asset, executes trades

mcp_server/
  server.py         FastMCP server; all tools call into etl/strategies/backtest/paper_trading

data/               Parquet fallback cache (only used when STORAGE_BACKEND=parquet)
notebooks/          Jupyter exploration notebooks (not tracked)
```

## Paper trading design

### Signal voting
Every poll fetches fresh data from yfinance, then aggregates two signal sources:

| Source | STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL |
|--------|-----------|-----|---------|------|-------------|
| TradingView | +2 BUY | +1 BUY | 0 | +1 SELL | +2 SELL |
| Each strategy (×4) | — | +1 BUY | 0 | +1 SELL | — |

Max 6 BUY votes / 6 SELL votes. Defaults: execute BUY at ≥3, SELL at ≥2.

### Position sizing
All available cash is invested in a single BUY (no partial allocation). One position per asset. Commission is 0.1% per trade, matching the backtest engine.

### Adaptive optimization
After every 3 SELL trades, `optimize_all()` runs a backtest grid search on 1y of daily QQQ data and saves the best parameters (by Sharpe ratio) to `paper_strategy_params`. The next poll automatically uses the updated params.

To manually trigger: `uv run python -m paper_trading --dry-run` shows current params in use; call `optimize_strategies` MCP tool to re-run anytime.

## Key design decisions

- **No TA library dependency**: all indicators are implemented directly in `indicators/technical.py` using pandas/numpy to avoid `pandas-ta` / `ta-lib` compatibility issues.
- **yfinance doesn't support 4h**: `fetcher.py` fetches 1h and resamples when `interval="4h"` or `"2h"`.
- **fastmcp pinned `<2.14`**: versions ≥2.14 introduced a `docket` dependency that breaks on `fakeredis>=2.26`. See global CLAUDE.md for the patch script.
- **MySQL schema**: one table per `asset_interval` (e.g., `nasdaq_1d`) with `datetime` as primary key. `upsert()` uses `INSERT ... ON DUPLICATE KEY UPDATE` so re-running the ETL is idempotent.
- **Strategies are stateless**: `generate_signals(df)` always operates on the full dataframe and returns a full Series — no hidden state between calls.
- **Paper trading always refreshes**: `signals.py` calls `fetch()` directly (bypass cache) on every poll so recommendations are never stale.

## Adding a new strategy

1. Create `strategies/my_strategy.py` inheriting `Strategy`, implement `generate_signals()`.
2. Add it to `REGISTRY` in `strategies/__init__.py`.
3. Add its parameter grid to `PARAM_GRIDS` in `paper_trading/optimizer.py`.
4. It's immediately available in the backtest CLI, all MCP tools, and paper trading — no other changes needed.

## TradingView exchange reference

| Symbol | exchange param | screener |
|--------|---------------|----------|
| QQQ    | NASDAQ        | america  |
| SPY    | AMEX          | america  |
| ^NDX   | NASDAQ        | america  |
| AAPL   | NASDAQ        | america  |
| BTC    | BINANCE       | crypto   |
