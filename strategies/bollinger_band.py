import pandas as pd

from indicators.technical import bollinger_bands
from strategies.base import Signal, Strategy


class BollingerBand(Strategy):
    """Mean-reversion on Bollinger Band touches (lower → BUY, upper → SELL)."""

    name = "bollinger_band"

    def __init__(self, period: int = 20, std: float = 2.0):
        self.period = period
        self.std = std

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        bb_upper, _, bb_lower = bollinger_bands(close, period=self.period, std=self.std)

        signals = self._empty_signals(df)
        # Price crosses below lower band → oversold, expect mean reversion up
        signals[(close < bb_lower) & (close.shift(1) >= bb_lower.shift(1))] = Signal.BUY
        # Price crosses above upper band → overbought, expect mean reversion down
        signals[(close > bb_upper) & (close.shift(1) <= bb_upper.shift(1))] = Signal.SELL

        return signals
