import pandas as pd

from indicators.technical import sma
from strategies.base import Signal, Strategy


class SmaCrossover(Strategy):
    """Golden cross / death cross on two SMAs."""

    name = "sma_crossover"

    def __init__(self, fast: int = 50, slow: int = 200):
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = sma(df["close"], self.fast)
        slow = sma(df["close"], self.slow)

        signals = self._empty_signals(df)
        prev_fast, prev_slow = fast.shift(1), slow.shift(1)

        signals[(fast > slow) & (prev_fast <= prev_slow)] = Signal.BUY
        signals[(fast < slow) & (prev_fast >= prev_slow)] = Signal.SELL

        return signals
