"""
Paper trading engine: execute orders and track portfolio state in MySQL.

One position per asset. BUY invests all available cash; SELL closes the position.
Commission is 0.1% per trade (matches backtest engine).

After every `optimize_after` SELL trades, strategy parameters are automatically
re-optimized via grid search and saved to paper_strategy_params.
"""

from etl.db import get_engine
from paper_trading.models import (
    clear_all,
    close_position,
    create_tables,
    fetch_realized_pnl,
    fetch_trades,
    get_all_positions,
    get_portfolio,
    get_position,
    init_portfolio,
    log_trade,
    open_position,
    update_portfolio_cash,
)

COMMISSION = 0.001  # 0.1% per trade


class PaperTradingEngine:
    def __init__(self, initial_capital: float = 10_000.0, optimize_after: int = 3):
        self.initial_capital = initial_capital
        self.optimize_after = optimize_after
        create_tables()
        with get_engine().begin() as conn:
            if get_portfolio(conn) is None:
                init_portfolio(conn, initial_capital)

    def execute_order(
        self,
        symbol: str,
        asset: str,
        action: str,
        price: float,
        signal_source: str = "manual",
    ) -> dict:
        action = action.upper()
        if action not in ("BUY", "SELL"):
            return {"error": f"Invalid action '{action}'. Must be BUY or SELL."}

        with get_engine().begin() as conn:
            portfolio = get_portfolio(conn)
            if portfolio is None:
                return {"error": "Portfolio not initialized."}

            cash = portfolio["cash"]
            position = get_position(conn, symbol)

            if action == "BUY":
                if position:
                    return {"error": f"Already holding {symbol}. Sell before buying again."}
                if cash <= 0:
                    return {"error": "No cash available. Sell an existing position first."}

                shares = cash * (1 - COMMISSION) / price
                new_cash = 0.0

                open_position(conn, symbol, asset, shares, price, signal_source)
                update_portfolio_cash(conn, new_cash)
                log_trade(conn, symbol, asset, "BUY", shares, price, new_cash, None, signal_source)

                return {
                    "action": "BUY",
                    "symbol": symbol,
                    "shares": round(shares, 6),
                    "price": round(price, 4),
                    "cash_invested": round(cash, 2),
                    "cash_remaining": 0.0,
                    "signal_source": signal_source,
                }

            else:  # SELL
                if not position:
                    return {"error": f"No open position in {symbol} to sell."}

                shares = position["shares"]
                net_proceeds = shares * price * (1 - COMMISSION)
                # P&L = proceeds net of both commissions vs cash originally spent
                original_cash = shares * position["entry_price"] / (1 - COMMISSION)
                pnl = net_proceeds - original_cash
                new_cash = cash + net_proceeds

                close_position(conn, symbol)
                update_portfolio_cash(conn, new_cash)
                log_trade(conn, symbol, asset, "SELL", shares, price, new_cash, pnl, signal_source)

                result = {
                    "action": "SELL",
                    "symbol": symbol,
                    "shares": round(shares, 6),
                    "price": round(price, 4),
                    "proceeds": round(net_proceeds, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((price / position["entry_price"] - 1) * 100, 2),
                    "cash_after": round(new_cash, 2),
                    "signal_source": signal_source,
                    "optimization_triggered": False,
                }

        # Auto-optimize outside the transaction so it doesn't block the trade
        from paper_trading.optimizer import should_optimize, optimize_all
        if should_optimize(self.optimize_after):
            try:
                optimize_all(asset=asset)
                result["optimization_triggered"] = True
            except Exception as e:
                result["optimization_error"] = str(e)

        return result

    def get_portfolio_snapshot(self, current_prices: dict[str, float]) -> dict:
        with get_engine().connect() as conn:
            portfolio = get_portfolio(conn)
            positions = get_all_positions(conn)
            realized_pnl = fetch_realized_pnl(conn)

        if portfolio is None:
            return {"error": "Portfolio not initialized."}

        cash = portfolio["cash"]
        initial = portfolio["initial_capital"]
        positions_value = 0.0
        unrealized_pnl = 0.0
        position_details = []

        for p in positions:
            sym = p["symbol"]
            current_price = current_prices.get(sym)
            if current_price:
                market_value = p["shares"] * current_price
                unreal = (current_price - p["entry_price"]) * p["shares"]
                unreal_pct = (current_price / p["entry_price"] - 1) * 100
            else:
                market_value = p["shares"] * p["entry_price"]
                unreal = 0.0
                unreal_pct = 0.0

            positions_value += market_value
            unrealized_pnl += unreal

            position_details.append({
                "symbol": sym,
                "asset": p["asset"],
                "shares": round(p["shares"], 6),
                "entry_price": round(p["entry_price"], 4),
                "current_price": round(current_price, 4) if current_price else None,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unreal, 2),
                "unrealized_pct": round(unreal_pct, 2),
                "signal_source": p["signal_source"],
                "entry_date": str(p["entry_date"]),
            })

        total_equity = cash + positions_value
        total_return_pct = (total_equity / initial - 1) * 100

        return {
            "cash": round(cash, 2),
            "initial_capital": round(initial, 2),
            "positions_value": round(positions_value, 2),
            "total_equity": round(total_equity, 2),
            "total_return_pct": round(total_return_pct, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
            "positions": position_details,
        }

    def get_trades(self, limit: int = 20) -> list[dict]:
        with get_engine().connect() as conn:
            rows = fetch_trades(conn, limit)
        result = []
        for t in rows:
            d = dict(t)
            if d.get("executed_at"):
                d["executed_at"] = str(d["executed_at"])
            if d.get("pnl") is not None:
                d["pnl"] = round(d["pnl"], 2)
            result.append(d)
        return result

    def reset(self, initial_capital: float = 10_000.0) -> dict:
        with get_engine().begin() as conn:
            clear_all(conn)
            init_portfolio(conn, initial_capital)
        return {"status": "reset", "initial_capital": initial_capital}
