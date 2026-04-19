import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

from core.indicators import Indicators
from core.patterns import PatternRecognition
from core.regime_detector import RegimeDetector, MarketRegime
from core.strategy_engine import (
    TrendFollowStrategy, MeanReversionStrategy,
    BreakoutStrategy, ScalpingStrategy, StrategySignal,
)


@dataclass
class TradeSignal:
    """Full enriched signal for the bot pipeline."""
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    symbol: str = ""
    strategy: str = ""
    regime: str = "UNKNOWN"
    timeframe_alignment: Dict[str, str] = field(default_factory=dict)
    confluence_factors: List[str] = field(default_factory=list)
    pattern_triggers: List[str] = field(default_factory=list)
    market_context: str = "RANGING"
    gate_results: Dict[str, bool] = field(default_factory=dict)


class SignalEngine:
    """
    v5.0 — Regime-aware multi-strategy signal engine.

    Pipeline:
      1. Detect market regime (TRENDING/RANGING/VOLATILE)
      2. Dispatch to appropriate strategy(ies) for that regime
      3. Run post-filters: MTFA, EMA 200 macro, VWAP, spread, volume
      4. Score and rank signals across all pairs
      5. Return top N highest-quality signals

    Strategy dispatch:
      TRENDING_BULL / TRENDING_BEAR -> TrendFollow (primary) + Scalping (secondary)
      RANGING                       -> MeanReversion (primary) + Breakout pre-check
      HIGH_VOLATILITY               -> Breakout (primary) + Scalping (secondary)
    """

    def __init__(self):
        self.indicators = Indicators()
        self.patterns = PatternRecognition()
        self.regime_detector = RegimeDetector()

        # Strategies
        self.trend_follow = TrendFollowStrategy()
        self.mean_reversion = MeanReversionStrategy()
        self.breakout = BreakoutStrategy()
        self.scalping = ScalpingStrategy()

        # Per-pair regime detectors (each pair has its own state machine)
        self._pair_regime_detectors: Dict[str, RegimeDetector] = {}

    # ── Main Entry Point ────────────────────────────────────

    def generate_signal(self, df_15m: pd.DataFrame,
                        df_1h: pd.DataFrame = None,
                        df_4h: pd.DataFrame = None,
                        symbol: str = "") -> Optional[TradeSignal]:
        """
        Generate a signal for a single pair using regime-aware strategy dispatch.
        """
        if df_15m is None or len(df_15m) < 30:
            return None

        # Compute indicators on primary timeframe
        ind = self.indicators.get_all_indicators(df_15m)

        # Detect regime for this specific pair
        detector = self._get_detector(symbol)
        regime = detector.detect(df_15m, ind)

        # Strategy dispatch based on regime
        strategy_signals = self._dispatch_strategies(df_15m, ind, regime)

        if not strategy_signals:
            return None

        # Take the best signal from dispatched strategies
        best = max(strategy_signals, key=lambda s: s.confidence)

        # Post-filters
        gate_results = {}

        # Gate: MTFA (higher timeframe trend agreement)
        tf_alignment = self._gate_mtfa(best.direction, ind, df_1h, df_4h)
        aligned_count = sum(1 for v in tf_alignment.values() if v == best.direction)
        gate_results["MTFA"] = aligned_count >= 1  # At least 1 higher TF agrees
        # For trend-follow, we're stricter
        if best.strategy == "TREND_FOLLOW" and aligned_count < 2:
            return None
        # For mean reversion, MTFA is less important (counter-trend by nature)
        if best.strategy != "MEAN_REVERSION" and aligned_count < 1:
            return None

        # Gate: EMA 200 macro (only for trend follow)
        if best.strategy == "TREND_FOLLOW":
            gate_results["EMA200"] = self._gate_ema200(best.direction, ind, df_1h)
            if not gate_results["EMA200"]:
                return None

        # Gate: Volume (already checked per-strategy, but double check anomalies)
        gate_results["VOLUME"] = self._gate_volume_check(ind)
        if not gate_results["VOLUME"]:
            return None

        # Gate: VWAP (soft — adds confidence)
        vwap_ok = self._gate_vwap(best.direction, ind)
        if vwap_ok:
            best.confluence_factors.append("VWAP position confirmed")
            best.confidence = min(best.confidence + 0.1, 1.0)

        # Enrich into TradeSignal
        return TradeSignal(
            direction=best.direction,
            entry_price=best.entry_price,
            stop_loss=best.stop_loss,
            take_profit=best.take_profit,
            confidence=best.confidence,
            symbol=symbol,
            strategy=best.strategy,
            regime=regime.value,
            timeframe_alignment=tf_alignment,
            confluence_factors=best.confluence_factors,
            pattern_triggers=best.pattern_triggers,
            market_context=ind.get("market_structure", "RANGING"),
            gate_results=gate_results,
        )

    # ── Multi-Pair Scanner ──────────────────────────────────

    def scan_multiple_pairs(self, pairs_data: Dict[str, Dict],
                            max_signals: int = 5) -> List[TradeSignal]:
        """
        Scan multiple pairs with regime-aware strategy dispatch.
        Returns top N signals ranked by confidence.
        """
        all_signals = []

        for symbol, data in pairs_data.items():
            signal = self.generate_signal(
                df_15m=data.get("15m"),
                df_1h=data.get("1h"),
                df_4h=data.get("4h"),
                symbol=symbol,
            )
            if signal is not None:
                all_signals.append(signal)

        all_signals.sort(key=lambda s: s.confidence, reverse=True)
        return all_signals[:max_signals]

    # ── Strategy Dispatch ───────────────────────────────────

    def _dispatch_strategies(self, df: pd.DataFrame, ind: Dict[str, Any],
                             regime: MarketRegime) -> List[StrategySignal]:
        """
        Dispatch to appropriate strategies based on detected regime.
        Each regime activates a primary and optional secondary strategy.
        """
        signals = []

        if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            # Primary: Trend Follow
            sig = self.trend_follow.evaluate(df, ind, regime)
            if sig:
                signals.append(sig)
            # Secondary: Scalping (momentum plays within trend)
            sig2 = self.scalping.evaluate(df, ind, regime)
            if sig2:
                signals.append(sig2)

        elif regime == MarketRegime.RANGING:
            # Primary: Mean Reversion
            sig = self.mean_reversion.evaluate(df, ind, regime)
            if sig:
                signals.append(sig)
            # Secondary: Breakout (catch the range break early)
            sig2 = self.breakout.evaluate(df, ind, regime)
            if sig2:
                signals.append(sig2)

        elif regime == MarketRegime.HIGH_VOLATILITY:
            # Primary: Breakout
            sig = self.breakout.evaluate(df, ind, regime)
            if sig:
                signals.append(sig)
            # Secondary: Scalping
            sig2 = self.scalping.evaluate(df, ind, regime)
            if sig2:
                signals.append(sig2)

        else:
            # Unknown regime: try scalping only (lowest commitment)
            sig = self.scalping.evaluate(df, ind, regime)
            if sig:
                signals.append(sig)

        return signals

    # ── Per-Pair Regime Detector ────────────────────────────

    def _get_detector(self, symbol: str) -> RegimeDetector:
        """Get or create a per-pair regime detector (each has its own state machine)."""
        if symbol not in self._pair_regime_detectors:
            self._pair_regime_detectors[symbol] = RegimeDetector()
        return self._pair_regime_detectors[symbol]

    # ── Post-Filters ────────────────────────────────────────

    def _gate_mtfa(self, primary_direction: str, ind_15m: Dict,
                   df_1h: pd.DataFrame = None,
                   df_4h: pd.DataFrame = None) -> Dict[str, str]:
        """Multi-timeframe alignment: higher TFs need trend agreement."""
        alignment = {"15m": primary_direction}

        if df_1h is not None and len(df_1h) >= 30:
            ind_1h = self.indicators.get_all_indicators(df_1h)
            alignment["1h"] = self._get_trend_bias(ind_1h) or "NEUTRAL"
        else:
            alignment["1h"] = primary_direction

        if df_4h is not None and len(df_4h) >= 30:
            ind_4h = self.indicators.get_all_indicators(df_4h)
            alignment["4h"] = self._get_trend_bias(ind_4h) or "NEUTRAL"
        else:
            alignment["4h"] = primary_direction

        return alignment

    @staticmethod
    def _get_trend_bias(ind: Dict[str, Any]) -> Optional[str]:
        ema20 = ind.get("ema_20", 0)
        ema50 = ind.get("ema_50", 0)
        di_plus = ind.get("di_plus", 0)
        di_minus = ind.get("di_minus", 0)

        if pd.isna(ema20) or pd.isna(ema50):
            return None

        if ema20 > ema50 and di_plus > di_minus:
            return "BUY"
        elif ema20 < ema50 and di_minus > di_plus:
            return "SELL"
        return None

    def _gate_ema200(self, direction: str, ind_15m: Dict,
                     df_1h: pd.DataFrame = None) -> bool:
        if df_1h is not None and len(df_1h) >= 200:
            ind_1h = self.indicators.get_all_indicators(df_1h)
            close = ind_1h.get("close", 0)
            ema200 = ind_1h.get("ema_200", 0)
        else:
            close = ind_15m.get("close", 0)
            ema200 = ind_15m.get("ema_200", 0)

        if pd.isna(close) or pd.isna(ema200) or ema200 <= 0:
            return True

        if direction == "BUY":
            return close > ema200
        return close < ema200

    @staticmethod
    def _gate_volume_check(ind: Dict[str, Any]) -> bool:
        """Reject trades during abnormally LOW volume periods."""
        current_vol = ind.get("current_volume", 0)
        vol_sma = ind.get("volume_sma", 0)

        if pd.isna(current_vol) or pd.isna(vol_sma) or vol_sma <= 0:
            return True  # No data, pass through

        ratio = current_vol / vol_sma
        # Reject if volume is less than 40% of average (dead market)
        return ratio >= 0.4

    @staticmethod
    def _gate_vwap(direction: str, ind: Dict[str, Any]) -> bool:
        close = ind.get("close", 0)
        vwap = ind.get("vwap", 0)

        if pd.isna(close) or pd.isna(vwap) or vwap <= 0:
            return False

        if direction == "BUY":
            return close > vwap
        return close < vwap
