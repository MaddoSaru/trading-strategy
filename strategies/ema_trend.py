import pandas as pd

from indicators.technical import ema, rsi
from strategies.base import Signal, Strategy


class EmaTrend(Strategy):
    """EMA 9/21 crossover with RSI trend filter — avoids trading against strong trend."""

    name = "ema_trend"

    def __init__(self, fast: int = 9, slow: int = 21, rsi_filter: int = 50):
        self.fast = fast
        self.slow = slow
        self.rsi_filter = rsi_filter

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ema = ema(df["close"], self.fast)
        slow_ema = ema(df["close"], self.slow)
        rsi_vals = rsi(df["close"])

        cross_up = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
        cross_down = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))

        signals = self._empty_signals(df)
        signals[cross_up & (rsi_vals > self.rsi_filter)] = Signal.BUY
        signals[cross_down & (rsi_vals < self.rsi_filter)] = Signal.SELL

        return signals
