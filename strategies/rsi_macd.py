import pandas as pd

from indicators.technical import macd, rsi
from strategies.base import Signal, Strategy


class RsiMacd(Strategy):
    """RSI oversold/overbought filter combined with MACD crossover entry."""

    name = "rsi_macd"

    def __init__(self, rsi_oversold: int = 35, rsi_overbought: int = 65):
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi_vals = rsi(df["close"])
        macd_line, signal_line, _ = macd(df["close"])

        macd_cross_up = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
        macd_cross_down = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))

        signals = self._empty_signals(df)
        signals[macd_cross_up & (rsi_vals < self.rsi_oversold)] = Signal.BUY
        signals[macd_cross_down & (rsi_vals > self.rsi_overbought)] = Signal.SELL

        return signals
