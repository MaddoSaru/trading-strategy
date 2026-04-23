"""
Strategy parameter optimizer: grid-search over each strategy's tunable parameters
using backtests on recent historical data, ranked by Sharpe ratio.

Triggered automatically after every N SELL trades. Results are persisted in
paper_strategy_params and loaded by signals.py on every poll.
"""

import itertools
import math
from datetime import datetime

from sqlalchemy import text

from backtest.engine import run_backtest
from etl.db import get_engine
from etl.fetcher import ASSETS, fetch
from etl.storage import save
from indicators.technical import add_indicators
from strategies import REGISTRY

# Parameter search space for each strategy.
# Keep grids small (~3 values per param) so 54 total backtests run in a few seconds.
PARAM_GRIDS: dict[str, dict[str, list]] = {
    "sma_crossover": {
        "fast": [10, 20, 50],
        "slow": [100, 150, 200],
    },
    "rsi_macd": {
        "rsi_oversold": [25, 30, 35],
        "rsi_overbought": [60, 65, 70],
    },
    "bollinger_band": {
        "period": [15, 20, 25],
        "std": [1.5, 2.0, 2.5],
    },
    "ema_trend": {
        "fast": [5, 9, 12],
        "slow": [15, 21, 26],
        "rsi_filter": [45, 50, 55],
    },
}

# Default params (mirrors strategy __init__ defaults)
DEFAULT_PARAMS: dict[str, dict] = {
    "sma_crossover": {"fast": 50, "slow": 200},
    "rsi_macd": {"rsi_oversold": 35, "rsi_overbought": 65},
    "bollinger_band": {"period": 20, "std": 2.0},
    "ema_trend": {"fast": 9, "slow": 21, "rsi_filter": 50},
}


def _valid_combo(strategy_name: str, params: dict) -> bool:
    if strategy_name in ("sma_crossover", "ema_trend"):
        return params.get("fast", 0) < params.get("slow", 1)
    if strategy_name == "rsi_macd":
        return params.get("rsi_oversold", 0) < params.get("rsi_overbought", 100)
    return True


def optimize_strategy(strategy_name: str, df) -> dict:
    """
    Grid-search strategy_name over PARAM_GRIDS using df.
    Returns: {params, sharpe_ratio, total_return_pct, combos_tested}
    """
    cls = REGISTRY[strategy_name]
    grid = PARAM_GRIDS.get(strategy_name, {})

    if not grid:
        defaults = DEFAULT_PARAMS.get(strategy_name, {})
        return {"params": defaults, "sharpe_ratio": None, "total_return_pct": None, "combos_tested": 0}

    keys = list(grid.keys())
    combos = [
        dict(zip(keys, vals))
        for vals in itertools.product(*[grid[k] for k in keys])
        if _valid_combo(strategy_name, dict(zip(keys, vals)))
    ]

    best_score = float("-inf")
    best_params = DEFAULT_PARAMS.get(strategy_name, {})
    best_sharpe = None
    best_return = None

    for params in combos:
        try:
            strategy = cls(**params)
            result = run_backtest(df, strategy)
            sharpe = result.sharpe_ratio
            score = sharpe if not math.isnan(sharpe) else float("-inf")
            if score > best_score:
                best_score = score
                best_params = params
                best_sharpe = round(sharpe, 4)
                best_return = round(result.total_return * 100, 2)
        except Exception:
            continue

    return {
        "params": best_params,
        "sharpe_ratio": best_sharpe,
        "total_return_pct": best_return,
        "combos_tested": len(combos),
    }


def optimize_all(asset: str = "nasdaq", interval: str = "1d", period: str = "1y") -> dict:
    """
    Optimize all strategies on fresh data for the given asset.
    Persists results to paper_strategy_params and returns a summary.
    """
    symbol = ASSETS.get(asset, asset.upper())
    df = fetch(symbol, interval=interval, period=period)
    save(df, symbol, interval)
    df = add_indicators(df)

    sell_count = _get_sell_count()
    results = {}

    with get_engine().begin() as conn:
        _ensure_table(conn)
        for name in REGISTRY:
            opt = optimize_strategy(name, df)
            import json
            conn.execute(text("""
                INSERT INTO paper_strategy_params
                    (strategy_name, params_json, sharpe_ratio, total_return_pct,
                     optimized_at, sell_count_at_optimization)
                VALUES
                    (:name, :params, :sharpe, :ret, :now, :sell_count)
                ON DUPLICATE KEY UPDATE
                    params_json = :params,
                    sharpe_ratio = :sharpe,
                    total_return_pct = :ret,
                    optimized_at = :now,
                    sell_count_at_optimization = :sell_count
            """), {
                "name": name,
                "params": json.dumps(opt["params"]),
                "sharpe": opt["sharpe_ratio"],
                "ret": opt["total_return_pct"],
                "now": datetime.utcnow(),
                "sell_count": sell_count,
            })
            results[name] = opt

    return {"asset": asset, "interval": interval, "period": period, "strategies": results}


def get_active_params(strategy_name: str) -> dict:
    """Return currently stored params for strategy_name, or defaults if not yet optimized."""
    import json
    try:
        with get_engine().connect() as conn:
            _ensure_table(conn)
            row = conn.execute(text("""
                SELECT params_json FROM paper_strategy_params
                WHERE strategy_name = :name
            """), {"name": strategy_name}).fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return DEFAULT_PARAMS.get(strategy_name, {})


def get_all_active_params() -> dict[str, dict]:
    """Return params for all strategies (optimized or defaults)."""
    return {name: get_active_params(name) for name in REGISTRY}


def should_optimize(optimize_after: int = 3) -> bool:
    """Return True if enough new SELL trades have occurred since last optimization."""
    sell_count = _get_sell_count()
    last_opt_count = _get_last_optimized_sell_count()
    return (sell_count - last_opt_count) >= optimize_after


def _get_sell_count() -> int:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM paper_trades WHERE action = 'SELL'"
            )).fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def _get_last_optimized_sell_count() -> int:
    try:
        with get_engine().connect() as conn:
            _ensure_table(conn)
            row = conn.execute(text(
                "SELECT MAX(sell_count_at_optimization) FROM paper_strategy_params"
            )).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _ensure_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS paper_strategy_params (
            id                          INT AUTO_INCREMENT PRIMARY KEY,
            strategy_name               VARCHAR(50)  NOT NULL,
            params_json                 TEXT         NOT NULL,
            sharpe_ratio                DOUBLE,
            total_return_pct            DOUBLE,
            optimized_at                DATETIME     NOT NULL,
            sell_count_at_optimization  INT          NOT NULL DEFAULT 0,
            UNIQUE KEY uq_strategy (strategy_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
