"""
MySQL connection and OHLCV upsert logic.

One table per asset+interval: nasdaq_1d, sp500_15m, nasdaq_index_1h, etc.
Each table has (symbol, name, datetime, open, high, low, close, volume)
with datetime as the sole primary key.

Required environment variables (defaults shown):
  MYSQL_HOST      localhost
  MYSQL_PORT      3306
  MYSQL_USER      root
  MYSQL_PASSWORD  (empty)
  MYSQL_DB        trading_strategy
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd
from sqlalchemy import create_engine, Engine, text
from sqlalchemy.dialects.mysql import insert as mysql_insert

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "trading_strategy")

_engine: Engine | None = None


def table_name(asset: str, interval: str) -> str:
    return f"{asset}_{interval}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _ensure_database()
        _engine = create_engine(
            f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}",
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def _ensure_database() -> None:
    tmp = create_engine(
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/",
    )
    try:
        with tmp.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}`"))
    finally:
        tmp.dispose()


def create_table(tbl: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{tbl}` (
                symbol    VARCHAR(10)  NOT NULL,
                name      VARCHAR(100) NOT NULL,
                datetime  DATETIME     NOT NULL,
                open      DOUBLE       NOT NULL,
                high      DOUBLE       NOT NULL,
                low       DOUBLE       NOT NULL,
                close     DOUBLE       NOT NULL,
                volume    DOUBLE       NOT NULL,
                PRIMARY KEY (datetime)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))


def drop_legacy_table() -> None:
    """Drop the old single ohlcv table if it still exists."""
    with get_engine().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS `ohlcv`"))


def _upsert_method(table, conn, keys, data_iter):
    data = [dict(zip(keys, row)) for row in data_iter]
    if not data:
        return
    stmt = mysql_insert(table.table).values(data)
    update_cols = {k: stmt.inserted[k] for k in keys if k != "datetime"}
    stmt = stmt.on_duplicate_key_update(**update_cols)
    conn.execute(stmt)


def upsert(df: pd.DataFrame, symbol: str, name: str, asset: str, interval: str) -> None:
    tbl = table_name(asset, interval)
    create_table(tbl)

    save_df = df[["open", "high", "low", "close", "volume"]].copy()
    save_df.insert(0, "symbol", symbol)
    save_df.insert(1, "name", name)
    save_df = save_df.reset_index()
    save_df["datetime"] = pd.to_datetime(save_df["datetime"]).dt.tz_localize(None)
    save_df = save_df[["symbol", "name", "datetime", "open", "high", "low", "close", "volume"]]

    save_df.to_sql(
        tbl,
        get_engine(),
        if_exists="append",
        index=False,
        method=_upsert_method,
        chunksize=500,
    )


def query(asset: str, interval: str) -> pd.DataFrame | None:
    tbl = table_name(asset, interval)
    try:
        sql = text(f"""
            SELECT datetime, open, high, low, close, volume
            FROM `{tbl}`
            ORDER BY datetime ASC
        """)
        with get_engine().connect() as conn:
            df = pd.read_sql(sql, conn)

        if df.empty:
            return None

        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        df.index.name = "datetime"
        return df
    except Exception:
        return None
