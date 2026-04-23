from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = 1
    HOLD = 0
    SELL = -1


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return a pd.Series of Signal values, indexed the same as df."""
        ...

    def _empty_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=df.index, dtype=object)
