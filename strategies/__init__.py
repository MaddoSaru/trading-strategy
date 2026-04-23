from strategies.bollinger_band import BollingerBand
from strategies.ema_trend import EmaTrend
from strategies.rsi_macd import RsiMacd
from strategies.sma_crossover import SmaCrossover

REGISTRY: dict[str, type] = {
    "sma_crossover": SmaCrossover,
    "rsi_macd": RsiMacd,
    "bollinger_band": BollingerBand,
    "ema_trend": EmaTrend,
}
