"""
Combined signal aggregation from TradingView recommendation + all strategies.

Data is always refreshed from yfinance before generating signals so every
recommendation uses the latest available market context.

Voting system (max 6 BUY votes, max 6 SELL votes):
  TradingView STRONG_BUY  → 2 BUY votes
  TradingView BUY         → 1 BUY vote
  TradingView NEUTRAL     → 0 votes
  TradingView SELL        → 1 SELL vote
  TradingView STRONG_SELL → 2 SELL votes
  Each strategy BUY/SELL  → 1 vote each (4 strategies × 1 = 4 possible)

Strategy parameters are loaded from paper_strategy_params (optimizer results).
Falls back to strategy defaults if not yet optimized.
"""

from tradingview_ta import TA_Handler, Interval as TVInterval

from etl.fetcher import ASSETS, fetch
from etl.storage import save
from indicators.technical import add_indicators
from paper_trading.optimizer import get_active_params
from strategies import REGISTRY

_TV_INTERVAL_MAP = {
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

_TV_EXCHANGES = {
    "QQQ": ("NASDAQ", "america"),
    "SPY": ("AMEX", "america"),
    "^NDX": ("NASDAQ", "america"),
    "^GSPC": ("SP:SPX", "america"),
}

_TV_BUY_VOTES = {"STRONG_BUY": 2, "BUY": 1, "NEUTRAL": 0, "SELL": 0, "STRONG_SELL": 0}
_TV_SELL_VOTES = {"STRONG_BUY": 0, "BUY": 0, "NEUTRAL": 0, "SELL": 1, "STRONG_SELL": 2}


def get_combined_signal(
    asset: str,
    interval: str = "1d",
    period: str = "2y",
    buy_threshold: int = 3,
    sell_threshold: int = 2,
) -> dict:
    """
    Refresh market data, then aggregate TradingView + strategy signals.
    Strategy instances use optimized params from paper_strategy_params when available.
    Returns a dict with action, vote counts, active params, and per-source breakdown.
    """
    symbol = ASSETS.get(asset, asset.upper())

    # Always fetch fresh data and upsert into storage
    df = fetch(symbol, interval=interval, period=period)
    save(df, symbol, interval)
    df = add_indicators(df)

    # --- TradingView ---
    tv_rec = "ERROR"
    tv_buy = tv_sell = 0
    try:
        exchange, screener = _TV_EXCHANGES.get(symbol, ("NASDAQ", "america"))
        handler = TA_Handler(
            symbol=symbol,
            screener=screener,
            exchange=exchange,
            interval=_TV_INTERVAL_MAP.get(interval, TVInterval.INTERVAL_1_DAY),
        )
        tv_rec = handler.get_analysis().summary["RECOMMENDATION"]
        tv_buy = _TV_BUY_VOTES.get(tv_rec, 0)
        tv_sell = _TV_SELL_VOTES.get(tv_rec, 0)
    except Exception as e:
        tv_rec = f"ERROR({e})"

    # --- Strategies with optimized params ---
    strategy_signals: dict[str, str] = {}
    active_params: dict[str, dict] = {}
    strat_buy = strat_sell = 0

    for name, cls in REGISTRY.items():
        params = get_active_params(name)
        active_params[name] = params
        sig = cls(**params).generate_signals(df).iloc[-1].name
        strategy_signals[name] = sig
        if sig == "BUY":
            strat_buy += 1
        elif sig == "SELL":
            strat_sell += 1

    total_buy = tv_buy + strat_buy
    total_sell = tv_sell + strat_sell

    if total_buy >= buy_threshold:
        action = "BUY"
    elif total_sell >= sell_threshold:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "asset": asset,
        "symbol": symbol,
        "interval": interval,
        "as_of": str(df.index[-1]),
        "close": round(float(df.iloc[-1]["close"]), 4),
        "action": action,
        "buy_votes": total_buy,
        "sell_votes": total_sell,
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
        "active_params": active_params,
        "breakdown": {
            "tradingview": {
                "recommendation": tv_rec,
                "buy_votes": tv_buy,
                "sell_votes": tv_sell,
            },
            "strategies": strategy_signals,
        },
    }
