"""
MySQL tables for paper trading state: portfolio, open positions, and trade log.
"""

from datetime import datetime

from sqlalchemy import text

from etl.db import get_engine


def create_tables() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_portfolio (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                cash            DOUBLE NOT NULL,
                initial_capital DOUBLE NOT NULL,
                created_at      DATETIME NOT NULL,
                updated_at      DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                symbol        VARCHAR(10)  NOT NULL,
                asset         VARCHAR(20)  NOT NULL,
                shares        DOUBLE       NOT NULL,
                entry_price   DOUBLE       NOT NULL,
                entry_date    DATETIME     NOT NULL,
                signal_source VARCHAR(200) NOT NULL,
                UNIQUE KEY uq_symbol (symbol)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                symbol        VARCHAR(10)  NOT NULL,
                asset         VARCHAR(20)  NOT NULL,
                action        VARCHAR(4)   NOT NULL,
                shares        DOUBLE       NOT NULL,
                price         DOUBLE       NOT NULL,
                cash_after    DOUBLE       NOT NULL,
                pnl           DOUBLE,
                signal_source VARCHAR(200),
                executed_at   DATETIME     NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))


def get_portfolio(conn) -> dict | None:
    row = conn.execute(text(
        "SELECT * FROM paper_portfolio ORDER BY id LIMIT 1"
    )).fetchone()
    return dict(row._mapping) if row else None


def init_portfolio(conn, initial_capital: float) -> None:
    now = datetime.utcnow()
    conn.execute(text("""
        INSERT INTO paper_portfolio (cash, initial_capital, created_at, updated_at)
        VALUES (:cash, :initial_capital, :now, :now)
    """), {"cash": initial_capital, "initial_capital": initial_capital, "now": now})


def update_portfolio_cash(conn, cash: float) -> None:
    conn.execute(text("""
        UPDATE paper_portfolio SET cash = :cash, updated_at = :now ORDER BY id LIMIT 1
    """), {"cash": cash, "now": datetime.utcnow()})


def get_all_positions(conn) -> list[dict]:
    rows = conn.execute(text("SELECT * FROM paper_positions")).fetchall()
    return [dict(r._mapping) for r in rows]


def get_position(conn, symbol: str) -> dict | None:
    row = conn.execute(text(
        "SELECT * FROM paper_positions WHERE symbol = :symbol"
    ), {"symbol": symbol}).fetchone()
    return dict(row._mapping) if row else None


def open_position(conn, symbol: str, asset: str, shares: float,
                  entry_price: float, signal_source: str) -> None:
    conn.execute(text("""
        INSERT INTO paper_positions (symbol, asset, shares, entry_price, entry_date, signal_source)
        VALUES (:symbol, :asset, :shares, :entry_price, :entry_date, :signal_source)
        ON DUPLICATE KEY UPDATE
            shares = :shares, entry_price = :entry_price,
            entry_date = :entry_date, signal_source = :signal_source
    """), {
        "symbol": symbol, "asset": asset, "shares": shares,
        "entry_price": entry_price, "entry_date": datetime.utcnow(),
        "signal_source": signal_source,
    })


def close_position(conn, symbol: str) -> None:
    conn.execute(text(
        "DELETE FROM paper_positions WHERE symbol = :symbol"
    ), {"symbol": symbol})


def log_trade(conn, symbol: str, asset: str, action: str, shares: float,
              price: float, cash_after: float, pnl: float | None,
              signal_source: str) -> None:
    conn.execute(text("""
        INSERT INTO paper_trades
            (symbol, asset, action, shares, price, cash_after, pnl, signal_source, executed_at)
        VALUES
            (:symbol, :asset, :action, :shares, :price, :cash_after, :pnl, :signal_source, :executed_at)
    """), {
        "symbol": symbol, "asset": asset, "action": action, "shares": shares,
        "price": price, "cash_after": cash_after, "pnl": pnl,
        "signal_source": signal_source, "executed_at": datetime.utcnow(),
    })


def fetch_trades(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(text("""
        SELECT * FROM paper_trades ORDER BY executed_at DESC LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]


def fetch_realized_pnl(conn) -> float:
    row = conn.execute(text(
        "SELECT COALESCE(SUM(pnl), 0) FROM paper_trades WHERE action = 'SELL'"
    )).fetchone()
    return float(row[0]) if row else 0.0


def clear_all(conn) -> None:
    conn.execute(text("DELETE FROM paper_trades"))
    conn.execute(text("DELETE FROM paper_positions"))
    conn.execute(text("DELETE FROM paper_portfolio"))
