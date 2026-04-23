"""
Storage backend for OHLCV data.

Set STORAGE_BACKEND=parquet to use local parquet files instead of MySQL.
Default is MySQL (requires MYSQL_* env vars — see etl/db.py).
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from etl.fetcher import ASSETS_BY_SYMBOL, SYMBOL_NAMES

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "mysql")

_DATA_DIR = Path(__file__).parent.parent / "data"


def save(df: pd.DataFrame, symbol: str, interval: str) -> None:
    if STORAGE_BACKEND == "mysql":
        from etl.db import upsert
        asset = ASSETS_BY_SYMBOL.get(symbol, symbol.lower().replace("^", ""))
        name = SYMBOL_NAMES.get(symbol, symbol)
        upsert(df, symbol, name, asset, interval)
    else:
        _save_parquet(df, symbol, interval)


def load(symbol: str, interval: str) -> pd.DataFrame | None:
    if STORAGE_BACKEND == "mysql":
        from etl.db import query
        asset = ASSETS_BY_SYMBOL.get(symbol, symbol.lower().replace("^", ""))
        return query(asset, interval)
    else:
        return _load_parquet(symbol, interval)


# ── Parquet helpers (used when STORAGE_BACKEND=parquet) ──────────────────────

def _save_parquet(df: pd.DataFrame, symbol: str, interval: str) -> Path:
    path = _DATA_DIR / symbol.replace("^", "") / f"{interval}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return path


def _load_parquet(symbol: str, interval: str) -> pd.DataFrame | None:
    path = _DATA_DIR / symbol.replace("^", "") / f"{interval}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)
