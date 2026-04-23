# trading-strategy

ETL + strategy engine for trading Nasdaq (QQQ) and S&P 500 (SPY). Fetches historical OHLCV data, computes technical indicators, generates buy/sell signals from pluggable strategies, runs backtests, and exposes everything as an MCP server so an AI assistant can reason about the markets directly.

Includes a paper trading engine that polls TradingView + internal strategy signals, executes simulated trades, and self-optimizes strategy parameters after every N closed positions.

## Features

- **4 built-in strategies**: SMA crossover, RSI+MACD, Bollinger Band mean-reversion, EMA trend
- **Full backtester**: Sharpe ratio, max drawdown, win rate, equity curve, per-trade log
- **Paper trading**: combined TradingView + strategy signal voting, automatic position management
- **Adaptive optimization**: grid-searches strategy parameters via backtest after every N sells
- **MCP server**: 13 tools exposable to Claude Code or any MCP-compatible AI client
- **Dual storage**: MySQL (default) or local parquet files

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- MySQL 8+ (or set `STORAGE_BACKEND=parquet` to skip)

## Setup

```bash
uv sync                   # Install dependencies
uv sync --extra dev       # Also install Jupyter + matplotlib for notebooks
```

### Environment variables

```bash
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=your_user
export MYSQL_PASSWORD=your_password
export MYSQL_DB=trading_strategy   # created automatically on first run
```

## Usage

### Fetch market data

```bash
# Fetch QQQ + SPY across all common intervals → MySQL
uv run python -m etl.pipeline

# Fetch a specific asset / interval / period
uv run python -m etl.pipeline --assets nasdaq --intervals 1h --period 5y
```

### Backtest a strategy

```bash
uv run python -m backtest.engine --strategy sma_crossover --asset nasdaq --interval 1d --period 5y
uv run python -m backtest.engine --strategy rsi_macd --asset sp500 --interval 4h --capital 50000
```

Available strategies: `sma_crossover`, `rsi_macd`, `bollinger_band`, `ema_trend`  
Available assets: `nasdaq` (QQQ), `sp500` (SPY), `nasdaq_index` (^NDX), `sp500_index` (^GSPC)  
Available intervals: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1wk`, `1mo`

### Paper trading

```bash
# Preview signals without executing trades
uv run python -m paper_trading --dry-run

# Run a live poll — executes trades when signal thresholds are met
uv run python -m paper_trading --assets nasdaq,sp500 --interval 1d

# Options
--buy-threshold  INT    Minimum BUY votes to execute (default: 3)
--sell-threshold INT    Minimum SELL votes to execute (default: 2)
--capital        FLOAT  Initial capital, applied on first run (default: 10000)
```

### MCP server

```bash
uv run python -m mcp_server.server
```

Register with Claude Code (credentials must be passed as `-e` flags at add time):

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

## Paper trading signal logic

Every poll fetches fresh market data, then aggregates votes from two sources:

| Source | STRONG_BUY | BUY | SELL | STRONG_SELL |
|--------|-----------|-----|------|-------------|
| TradingView | +2 | +1 | +1 | +2 |
| Each strategy (×4) | — | +1 | +1 | — |

Max 6 votes in each direction. Default: execute BUY at ≥3 votes, SELL at ≥2 votes. All available cash is invested on BUY (0.1% commission, one position per asset).

After every 3 SELL trades the engine automatically grid-searches all strategy parameters on 1 year of daily data (~54 backtest combinations, ~1s) and saves the best params by Sharpe ratio. The next poll uses the updated parameters.

## Adding a strategy

1. Create `strategies/my_strategy.py` inheriting `Strategy`, implement `generate_signals(df)`.
2. Register it in `strategies/__init__.py` → `REGISTRY`.
3. Add its parameter grid to `PARAM_GRIDS` in `paper_trading/optimizer.py`.

The strategy is immediately available in the backtest CLI, all MCP tools, and paper trading.

## Project structure

```
etl/            Data pipeline — fetch, store, and load OHLCV data
indicators/     Technical indicators (pure pandas, no ta-lib)
strategies/     Pluggable signal strategies + REGISTRY
backtest/       Backtesting engine with performance metrics
paper_trading/  Paper trading engine, signal aggregation, optimizer, CLI
mcp_server/     FastMCP server exposing all tools to AI clients
data/           Local parquet cache (STORAGE_BACKEND=parquet only)
notebooks/      Jupyter exploration notebooks
```
