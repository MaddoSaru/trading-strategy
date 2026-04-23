import pandas as pd
import yfinance as yf
from datetime import datetime

ASSETS = {
    "nasdaq": "QQQ",
    "sp500": "SPY",
    "nasdaq_index": "^NDX",
    "sp500_index": "^GSPC",
}

SYMBOL_NAMES = {
    "QQQ":   "Invesco QQQ Trust (Nasdaq 100)",
    "SPY":   "SPDR S&P 500 ETF Trust",
    "^NDX":  "Nasdaq 100 Index",
    "^GSPC": "S&P 500 Index",
}

# Reverse lookup: ticker symbol → asset key used for table naming
ASSETS_BY_SYMBOL = {v: k for k, v in ASSETS.items()}

# Synthetic intervals not natively supported by yfinance → fetch 1h and resample
_RESAMPLE_MAP = {
    "4h": ("1h", "4h"),
    "2h": ("1h", "2h"),
}

# yfinance hard limits on how far back intraday data goes
_MAX_PERIOD = {
    "1m": "7d",
    "2m": "60d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
    "1h":  "730d",
}


def fetch(
    symbol: str,
    interval: str = "1d",
    period: str = "2y",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    source_interval, resample_rule = _RESAMPLE_MAP.get(interval, (interval, None))

    ticker = yf.Ticker(symbol)
    kwargs: dict = {"interval": source_interval}
    if start:
        kwargs["start"] = start
        kwargs["end"] = end or datetime.now().strftime("%Y-%m-%d")
    else:
        kwargs["period"] = _MAX_PERIOD.get(source_interval, period)

    df = ticker.history(**kwargs)
    df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
    df.index.name = "datetime"
    df.columns = df.columns.str.lower()
    df = df[["open", "high", "low", "close", "volume"]]

    if resample_rule:
        df = resample_ohlcv(df, resample_rule)

    return df.dropna()


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
