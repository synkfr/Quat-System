import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
from enum import Enum

from core.indicators import Indicators


class MarketRegime(Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class RegimeDetector:
    """
    Market regime detection using ADX, Bollinger Band width, ATR, and EMA stack.
    Acts as a state machine: regime persists for a minimum number of bars to prevent
    flip-flopping on noise.

    Regime logic:
      ADX > 25 + DI separation > 10  -> TRENDING (BULL or BEAR based on DI+/DI-)
      ADX < 20 + BB width contracting -> RANGING
      ATR spike (> 2x SMA) + ADX > 20 -> HIGH_VOLATILITY
      else                             -> RANGING (default safe state)
    """

    def __init__(self):
        self.indicators = Indicators()
        self._current_regime = MarketRegime.UNKNOWN
        self._regime_bars = 0
        self._min_persistence = 3  # Minimum bars before regime can change

        # Thresholds
        self.adx_trending = 25
        self.adx_ranging = 20
        self.di_separation = 10
        self.atr_spike_ratio = 1.8
        self.bb_squeeze_percentile = 30  # BB width below 30th percentile = squeeze

    def detect(self, df: pd.DataFrame, indicators: Dict[str, Any] = None) -> MarketRegime:
        """
        Detect current market regime from OHLCV data + pre-computed indicators.
        If indicators are provided, uses them directly. Otherwise computes its own.
        """
        if df is None or len(df) < 30:
            return MarketRegime.UNKNOWN

        if indicators is None:
            indicators = self.indicators.get_all_indicators(df)

        adx = indicators.get("adx", 0)
        di_plus = indicators.get("di_plus", 0)
        di_minus = indicators.get("di_minus", 0)
        atr = indicators.get("atr", 0)
        bb_upper = indicators.get("bb_upper", 0)
        bb_lower = indicators.get("bb_lower", 0)
        close = indicators.get("close", 0)

        if pd.isna(adx) or pd.isna(atr):
            return MarketRegime.UNKNOWN

        # Calculate BB width percentage
        bb_width = (bb_upper - bb_lower) / close * 100 if close > 0 else 0

        # Calculate ATR ratio vs its own SMA
        series = indicators.get("_series", {})
        atr_series = series.get("atr")
        atr_ratio = 1.0
        if atr_series is not None and len(atr_series) >= 20:
            atr_sma = atr_series.rolling(20).mean().iloc[-1]
            if not pd.isna(atr_sma) and atr_sma > 0:
                atr_ratio = atr / atr_sma

        # BB width historical percentile
        bb_series = series.get("bb")
        bb_squeeze = False
        if bb_series is not None:
            bb_width_series = (bb_series["upper"] - bb_series["lower"]) / df["close"] * 100
            bb_width_series = bb_width_series.dropna()
            if len(bb_width_series) >= 20:
                percentile = (bb_width_series < bb_width).mean() * 100
                bb_squeeze = percentile < self.bb_squeeze_percentile

        # Determine raw regime
        di_sep = abs(di_plus - di_minus)
        raw_regime = self._classify(adx, di_plus, di_minus, di_sep,
                                     atr_ratio, bb_squeeze)

        # Persistence: don't flip-flop
        if raw_regime == self._current_regime:
            self._regime_bars += 1
        else:
            self._regime_bars += 1
            if self._regime_bars >= self._min_persistence:
                self._current_regime = raw_regime
                self._regime_bars = 0

        # On first detection, set immediately
        if self._current_regime == MarketRegime.UNKNOWN:
            self._current_regime = raw_regime
            self._regime_bars = 0

        return self._current_regime

    def _classify(self, adx: float, di_plus: float, di_minus: float,
                  di_sep: float, atr_ratio: float, bb_squeeze: bool) -> MarketRegime:
        """Raw classification without persistence."""
        # HIGH_VOLATILITY: ATR spiking + some directional movement
        if atr_ratio >= self.atr_spike_ratio and adx > self.adx_ranging:
            return MarketRegime.HIGH_VOLATILITY

        # TRENDING: strong ADX + clear DI separation
        if adx > self.adx_trending and di_sep > self.di_separation:
            if di_plus > di_minus:
                return MarketRegime.TRENDING_BULL
            else:
                return MarketRegime.TRENDING_BEAR

        # RANGING: weak ADX or BB squeeze
        if adx < self.adx_ranging or bb_squeeze:
            return MarketRegime.RANGING

        # Default: ranging (safe state)
        return MarketRegime.RANGING

    def get_regime_info(self, df: pd.DataFrame,
                        indicators: Dict[str, Any] = None) -> Dict[str, Any]:
        """Full regime info for dashboard display."""
        regime = self.detect(df, indicators)

        if indicators is None:
            indicators = self.indicators.get_all_indicators(df)

        return {
            "regime": regime.value,
            "adx": round(indicators.get("adx", 0), 1),
            "di_plus": round(indicators.get("di_plus", 0), 1),
            "di_minus": round(indicators.get("di_minus", 0), 1),
            "atr": round(indicators.get("atr", 0), 2),
            "bb_width": round(
                (indicators.get("bb_upper", 0) - indicators.get("bb_lower", 0))
                / max(indicators.get("close", 1), 1) * 100, 2
            ),
            "persistence_bars": self._regime_bars,
            "recommended_strategy": self._recommend_strategy(regime),
        }

    @staticmethod
    def _recommend_strategy(regime: MarketRegime) -> str:
        mapping = {
            MarketRegime.TRENDING_BULL: "TREND_FOLLOW",
            MarketRegime.TRENDING_BEAR: "TREND_FOLLOW",
            MarketRegime.RANGING: "MEAN_REVERSION",
            MarketRegime.HIGH_VOLATILITY: "BREAKOUT",
            MarketRegime.UNKNOWN: "NONE",
        }
        return mapping.get(regime, "NONE")
