# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ETL + strategy engine for trading Nasdaq (QQQ) and S&P 500 (SPY). It fetches historical OHLCV data via yfinance, computes technical indicators, generates buy/sell signals from pluggable strategies, runs backtests, and exposes everything as an MCP server so Claude can reason about the markets directly.

It also includes a paper trading engine that polls TradingView + strategy signals, executes simulated trades, and self-optimizes strategy parameters after every N closed positions.

## Setup

```bash
uv sync                   # Install dependencies (creates .venv automatically)
uv sync --extra dev       # Also install Jupyter + matplotlib for notebooks
```

Set these environment variables (database is auto-created on first run):

```bash
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=your_user
export MYSQL_PASSWORD=your_password
export MYSQL_DB=trading_strategy
```

Set `STORAGE_BACKEND=parquet` to bypass MySQL and use local parquet files instead.

### MCP server registration

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
# ETL
uv run python -m etl.pipeline
uv run python -m etl.pipeline --assets nasdaq --intervals 1h --period 5y

# Backtest
uv run python -m backtest.engine --strategy sma_crossover --asset nasdaq --interval 1d --period 5y
uv run python -m backtest.engine --strategy rsi_macd --asset sp500 --interval 4h --capital 50000

# Paper trading
uv run python -m paper_trading --dry-run
uv run python -m paper_trading --assets nasdaq,sp500 --interval 1d

# MCP server (stdio transport, used by Claude Code)
uv run python -m mcp_server.server
```

## Architecture

### Data flow

```
yfinance → etl/fetcher.py → etl/storage.py → MySQL (or parquet)
                                    ↓
                         indicators/technical.py (add_indicators)
                                    ↓
                    strategies/*.py (generate_signals)
                                    ↓
              backtest/engine.py ──── paper_trading/engine.py
                                    ↓
                          mcp_server/server.py (exposes all above as tools)
```

### Key modules

**`etl/`** — `storage.py` is the unified interface; `db.py` handles MySQL with one table per `asset_interval` (e.g. `nasdaq_1d`), using `INSERT ... ON DUPLICATE KEY UPDATE` so the ETL is idempotent. `fetcher.py` resamples 1h data to synthesize 4h/2h intervals (yfinance doesn't support them natively).

**`indicators/technical.py`** — All indicators implemented directly in pandas/numpy (no `ta-lib` / `pandas-ta`). `add_indicators()` adds all columns to a df copy and is the canonical way to enrich a raw OHLCV frame.

**`strategies/`** — Stateless: `generate_signals(df)` takes the full DataFrame and returns a full `Signal` Series (no hidden state). `REGISTRY` in `__init__.py` is the single source of truth — adding a strategy there makes it available everywhere.

**`paper_trading/`** — `signals.py` always calls `fetch()` directly (no cache) so every recommendation uses live data. `engine.py` auto-triggers `optimizer.py` after every N SELL trades. `optimizer.py` grid-searches `PARAM_GRIDS` (~54 combos) and persists the best params (by Sharpe) to `paper_strategy_params`; `signals.py` loads them on every poll.

### MCP tools (mcp_server/server.py)

| Tool | Purpose |
|------|---------|
| `get_tv_analysis` | TradingView recommendation + 15+ indicators |
| `fetch_historical_data` | Download & cache OHLCV with indicators |
| `get_current_signals` | All strategies' current BUY/SELL/HOLD |
| `backtest_strategy` | Sharpe, drawdown, win rate, trade log |
| `compare_strategies` | All strategies ranked by return |
| `list_strategies` | Strategies + tunable parameters |
| `get_paper_portfolio` | Cash, positions, unrealized/realized P&L |
| `get_paper_trades` | Trade log |
| `execute_paper_order` | Manual paper BUY/SELL at current price |
| `run_paper_poll` | Check signals + execute if thresholds met |
| `get_strategy_params` | Active params per strategy (optimized vs defaults) |
| `optimize_strategies` | Manually trigger full parameter grid search |
| `reset_paper_portfolio` | Wipe paper data and start fresh |

## Paper trading signal logic

Two sources vote on each poll. Max 6 BUY and 6 SELL votes total:

| Source | STRONG_BUY | BUY | SELL | STRONG_SELL |
|--------|-----------|-----|------|-------------|
| TradingView | +2 | +1 | +1 | +2 |
| Each strategy (×4) | — | +1 | +1 | — |

Default thresholds: execute BUY at ≥3 votes, SELL at ≥2 votes. All cash is invested on BUY (one position per asset, 0.1% commission).

## Adding a new strategy

1. Create `strategies/my_strategy.py` inheriting `Strategy`, implement `generate_signals(df)`.
2. Add to `REGISTRY` in `strategies/__init__.py`.
3. Add its parameter grid to `PARAM_GRIDS` in `paper_trading/optimizer.py`.

The strategy is then immediately available in the backtest CLI, all MCP tools, and paper trading.

## TradingView exchange reference

| Symbol | exchange | screener |
|--------|----------|----------|
| QQQ | NASDAQ | america |
| SPY | AMEX | america |
| ^NDX | NASDAQ | america |
| AAPL | NASDAQ | america |
| BTC | BINANCE | crypto |

## fastmcp version pin

`fastmcp` is pinned `<2.14` — versions ≥2.14 introduced a `docket` dependency that breaks on `fakeredis>=2.26`. If MCP tools fail to connect, see the global CLAUDE.md for the patch script.
