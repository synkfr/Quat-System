import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from core.indicators import Indicators
from core.patterns import PatternRecognition
from core.regime_detector import MarketRegime


@dataclass
class StrategySignal:
    """Signal produced by a single strategy."""
    direction: str          # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float       # 0.0 - 1.0
    strategy: str           # Which strategy produced this
    confluence_factors: List[str] = field(default_factory=list)
    pattern_triggers: List[str] = field(default_factory=list)


class TrendFollowStrategy:
    """
    Deploy in TRENDING regimes.
    Entry: EMA 20 > EMA 50 > EMA 200 (bull) + price pullback to EMA 20/50.
    Confirmation: MACD histogram positive + RSI 40-70 (not overbought).
    """

    def evaluate(self, df: pd.DataFrame, ind: Dict[str, Any],
                 regime: MarketRegime) -> Optional[StrategySignal]:
        if regime not in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            return None

        close = ind.get("close", 0)
        ema20 = ind.get("ema_20", 0)
        ema50 = ind.get("ema_50", 0)
        ema200 = ind.get("ema_200", 0)
        rsi = ind.get("rsi", 50)
        macd_hist = ind.get("macd_hist", 0)
        atr = ind.get("atr", 0)
        adx = ind.get("adx", 0)

        if pd.isna(ema20) or pd.isna(ema50) or pd.isna(close):
            return None

        confluence = []
        direction = None

        # BULLISH TREND FOLLOW
        if regime == MarketRegime.TRENDING_BULL:
            # EMA stack: 20 > 50 (200 may not be available for all pairs)
            if ema20 > ema50:
                confluence.append(f"EMA stack bullish: {ema20:.0f} > {ema50:.0f}")
            else:
                return None

            # Price pullback to EMA 20 or 50 (within 0.5%)
            near_ema20 = abs(close - ema20) / close < 0.005
            near_ema50 = abs(close - ema50) / close < 0.01
            price_above = close > ema20

            if near_ema20 or near_ema50:
                confluence.append("Price at EMA pullback zone")
            elif price_above:
                # Still valid if price is above and RSI is not extreme
                confluence.append("Price above EMA stack, momentum continuation")
            else:
                return None

            # MACD confirmation
            if not pd.isna(macd_hist) and macd_hist > 0:
                confluence.append(f"MACD histogram positive: {macd_hist:.2f}")
            else:
                return None

            # RSI filter: not overbought, ideally 40-65
            if not pd.isna(rsi) and 35 < rsi < 70:
                confluence.append(f"RSI healthy zone: {rsi:.1f}")
            elif not pd.isna(rsi) and rsi >= 70:
                return None  # Overbought, skip

            direction = "BUY"

        # BEARISH TREND FOLLOW
        elif regime == MarketRegime.TRENDING_BEAR:
            if ema20 < ema50:
                confluence.append(f"EMA stack bearish: {ema20:.0f} < {ema50:.0f}")
            else:
                return None

            near_ema20 = abs(close - ema20) / close < 0.005
            near_ema50 = abs(close - ema50) / close < 0.01
            price_below = close < ema20

            if near_ema20 or near_ema50:
                confluence.append("Price at EMA pullback zone")
            elif price_below:
                confluence.append("Price below EMA stack, momentum continuation")
            else:
                return None

            if not pd.isna(macd_hist) and macd_hist < 0:
                confluence.append(f"MACD histogram negative: {macd_hist:.2f}")
            else:
                return None

            if not pd.isna(rsi) and 30 < rsi < 65:
                confluence.append(f"RSI healthy zone: {rsi:.1f}")
            elif not pd.isna(rsi) and rsi <= 30:
                return None

            direction = "SELL"

        if direction is None:
            return None

        # Calculate SL/TP
        if pd.isna(atr) or atr <= 0:
            atr = close * 0.01

        # Trend follow: tighter SL (1.5 ATR), let TP run (1:3 when strong trend)
        rr = 3.0 if (not pd.isna(adx) and adx > 30) else 2.0
        if direction == "BUY":
            sl = close - 1.5 * atr
            tp = close + risk_reward(close, sl, rr)
        else:
            sl = close + 1.5 * atr
            tp = close - risk_reward(close, sl, rr)

        confidence = min(len(confluence) / 5.0, 1.0)

        return StrategySignal(
            direction=direction, entry_price=close,
            stop_loss=sl, take_profit=tp,
            confidence=confidence, strategy="TREND_FOLLOW",
            confluence_factors=confluence,
        )


class MeanReversionStrategy:
    """
    Deploy in RANGING regimes.
    Entry: RSI < 30 at support (buy) or RSI > 70 at resistance (sell).
    Confirmation: Price near BB band + StochRSI crossover.
    """

    def evaluate(self, df: pd.DataFrame, ind: Dict[str, Any],
                 regime: MarketRegime) -> Optional[StrategySignal]:
        if regime != MarketRegime.RANGING:
            return None

        close = ind.get("close", 0)
        rsi = ind.get("rsi", 50)
        rsi_prev = ind.get("rsi_prev", 50)
        bb_upper = ind.get("bb_upper", 0)
        bb_lower = ind.get("bb_lower", 0)
        stoch_cross = ind.get("stoch_crossover", "NONE")
        atr = ind.get("atr", 0)
        supports = ind.get("support_levels", [])
        resistances = ind.get("resistance_levels", [])

        if pd.isna(rsi) or pd.isna(close):
            return None

        confluence = []
        direction = None

        # BULLISH MEAN REVERSION (buy at support/oversold)
        if rsi < 35 and rsi > rsi_prev:  # Oversold AND curling up
            confluence.append(f"RSI oversold + curling up: {rsi:.1f}")

            # Near lower BB
            if not pd.isna(bb_lower) and close <= bb_lower * 1.005:
                confluence.append("Price at lower Bollinger Band")

            # Near support level
            near_support = any(
                abs(close - s) / s < 0.01 for s in supports if s > 0
            )
            if near_support:
                confluence.append("Price near support level")

            # StochRSI bonus
            if stoch_cross == "BULLISH_CROSS":
                confluence.append("StochRSI bullish crossover")

            if len(confluence) >= 2:
                direction = "BUY"

        # BEARISH MEAN REVERSION (sell at resistance/overbought)
        elif rsi > 65 and rsi < rsi_prev:  # Overbought AND curling down
            confluence.append(f"RSI overbought + curling down: {rsi:.1f}")

            if not pd.isna(bb_upper) and close >= bb_upper * 0.995:
                confluence.append("Price at upper Bollinger Band")

            near_resistance = any(
                abs(close - r) / r < 0.01 for r in resistances if r > 0
            )
            if near_resistance:
                confluence.append("Price near resistance level")

            if stoch_cross == "BEARISH_CROSS":
                confluence.append("StochRSI bearish crossover")

            if len(confluence) >= 2:
                direction = "SELL"

        if direction is None:
            return None

        if pd.isna(atr) or atr <= 0:
            atr = close * 0.01

        # Mean reversion: tight SL (1 ATR), moderate TP (1:2)
        if direction == "BUY":
            sl = close - 1.0 * atr
            tp = close + risk_reward(close, sl, 2.0)
        else:
            sl = close + 1.0 * atr
            tp = close - risk_reward(close, sl, 2.0)

        confidence = min(len(confluence) / 4.0, 1.0)

        return StrategySignal(
            direction=direction, entry_price=close,
            stop_loss=sl, take_profit=tp,
            confidence=confidence, strategy="MEAN_REVERSION",
            confluence_factors=confluence,
        )


class BreakoutStrategy:
    """
    Deploy in HIGH_VOLATILITY regimes or when BB squeeze releases.
    Entry: Price breaks key S/R level with volume confirmation.
    Confirmation: MACD + ADX acceleration.
    """

    def __init__(self):
        self.patterns = PatternRecognition()

    def evaluate(self, df: pd.DataFrame, ind: Dict[str, Any],
                 regime: MarketRegime) -> Optional[StrategySignal]:
        if regime not in (MarketRegime.HIGH_VOLATILITY, MarketRegime.RANGING):
            return None

        close = ind.get("close", 0)
        atr = ind.get("atr", 0)
        adx = ind.get("adx", 0)
        macd_cross = ind.get("macd_crossover", "NONE")
        current_vol = ind.get("current_volume", 0)
        vol_sma = ind.get("volume_sma", 0)
        supports = ind.get("support_levels", [])
        resistances = ind.get("resistance_levels", [])
        bb_upper = ind.get("bb_upper", 0)
        bb_lower = ind.get("bb_lower", 0)

        if pd.isna(close):
            return None

        confluence = []
        direction = None

        # Volume spike required for any breakout
        volume_surge = False
        if not pd.isna(current_vol) and not pd.isna(vol_sma) and vol_sma > 0:
            vol_ratio = current_vol / vol_sma
            if vol_ratio > 1.5:
                volume_surge = True
                confluence.append(f"Volume surge: {vol_ratio:.1f}x avg")

        if not volume_surge:
            return None  # Fakeout filter: no volume = no breakout

        # Check for breakout patterns
        all_sr = supports + resistances
        breakout_patterns = self.patterns.detect_breakout_retest(df, all_sr)
        liq_patterns = self.patterns.detect_liquidity_grab(df, all_sr)

        recent_breakouts = [p for p in breakout_patterns if p["index"] >= len(df) - 3]
        recent_liq = [p for p in liq_patterns if p["index"] >= len(df) - 3]

        # Bullish breakout
        if any(p["direction"] == "BUY" for p in recent_breakouts):
            confluence.append("Breakout-retest pattern (bull)")
            direction = "BUY"
        elif any(p["direction"] == "BUY" for p in recent_liq):
            confluence.append("Liquidity grab pattern (bull)")
            direction = "BUY"
        # BB breakout
        elif not pd.isna(bb_upper) and close > bb_upper:
            confluence.append("Bollinger Band upper breakout")
            direction = "BUY"

        # Bearish breakout
        if direction is None:
            if any(p["direction"] == "SELL" for p in recent_breakouts):
                confluence.append("Breakout-retest pattern (bear)")
                direction = "SELL"
            elif any(p["direction"] == "SELL" for p in recent_liq):
                confluence.append("Liquidity grab pattern (bear)")
                direction = "SELL"
            elif not pd.isna(bb_lower) and close < bb_lower:
                confluence.append("Bollinger Band lower breakout")
                direction = "SELL"

        if direction is None:
            return None

        # ADX confirmation (breakouts need momentum)
        if not pd.isna(adx) and adx > 20:
            confluence.append(f"ADX momentum: {adx:.1f}")

        # MACD agreement
        if direction == "BUY" and macd_cross == "BULLISH_CROSS":
            confluence.append("MACD bullish crossover")
        elif direction == "SELL" and macd_cross == "BEARISH_CROSS":
            confluence.append("MACD bearish crossover")

        if len(confluence) < 2:
            return None  # Need at least 2 confirmations

        if pd.isna(atr) or atr <= 0:
            atr = close * 0.01

        # Breakout: wider SL (2 ATR), aggressive TP (1:3)
        if direction == "BUY":
            sl = close - 2.0 * atr
            tp = close + risk_reward(close, sl, 3.0)
        else:
            sl = close + 2.0 * atr
            tp = close - risk_reward(close, sl, 3.0)

        confidence = min(len(confluence) / 5.0, 1.0)

        return StrategySignal(
            direction=direction, entry_price=close,
            stop_loss=sl, take_profit=tp,
            confidence=confidence, strategy="BREAKOUT",
            confluence_factors=confluence,
            pattern_triggers=[p["pattern"] for p in (recent_breakouts + recent_liq)[:2]],
        )


class ScalpingStrategy:
    """
    Deploy during high momentum periods on lower timeframes.
    Entry: Strong MACD crossover + StochRSI confirmation + volume.
    Tight SL, quick TP (1:1.5).
    """

    def evaluate(self, df: pd.DataFrame, ind: Dict[str, Any],
                 regime: MarketRegime) -> Optional[StrategySignal]:
        # Scalping works in trending AND volatile regimes
        if regime == MarketRegime.UNKNOWN:
            return None

        close = ind.get("close", 0)
        rsi = ind.get("rsi", 50)
        macd_cross = ind.get("macd_crossover", "NONE")
        stoch_cross = ind.get("stoch_crossover", "NONE")
        macd_hist = ind.get("macd_hist", 0)
        atr = ind.get("atr", 0)
        current_vol = ind.get("current_volume", 0)
        vol_sma = ind.get("volume_sma", 0)
        obv_trend = ind.get("obv_trend", "FLAT")

        if pd.isna(close) or macd_cross == "NONE":
            return None

        confluence = []
        direction = None

        # Need MACD crossover as the primary trigger
        if macd_cross == "BULLISH_CROSS":
            direction = "BUY"
            confluence.append("MACD bullish crossover")
        elif macd_cross == "BEARISH_CROSS":
            direction = "SELL"
            confluence.append("MACD bearish crossover")
        else:
            return None

        # MUST have StochRSI agreement
        if direction == "BUY" and stoch_cross == "BULLISH_CROSS":
            confluence.append("StochRSI bullish confirmation")
        elif direction == "SELL" and stoch_cross == "BEARISH_CROSS":
            confluence.append("StochRSI bearish confirmation")
        else:
            return None  # No StochRSI confirmation = no scalp

        # Volume above average
        if not pd.isna(current_vol) and not pd.isna(vol_sma) and vol_sma > 0:
            if current_vol > vol_sma:
                confluence.append(f"Volume above avg: {current_vol / vol_sma:.1f}x")
            else:
                return None  # Low volume, skip

        # OBV agreement
        if direction == "BUY" and obv_trend == "RISING":
            confluence.append("OBV rising")
        elif direction == "SELL" and obv_trend == "FALLING":
            confluence.append("OBV falling")

        # RSI sanity check
        if direction == "BUY" and not pd.isna(rsi) and rsi > 75:
            return None  # Too overbought for a scalp entry
        if direction == "SELL" and not pd.isna(rsi) and rsi < 25:
            return None

        if len(confluence) < 3:
            return None

        if pd.isna(atr) or atr <= 0:
            atr = close * 0.01

        # Scalp: tight SL (0.75 ATR), quick TP (1:1.5)
        if direction == "BUY":
            sl = close - 0.75 * atr
            tp = close + risk_reward(close, sl, 1.5)
        else:
            sl = close + 0.75 * atr
            tp = close - risk_reward(close, sl, 1.5)

        confidence = min(len(confluence) / 5.0, 1.0)

        return StrategySignal(
            direction=direction, entry_price=close,
            stop_loss=sl, take_profit=tp,
            confidence=confidence, strategy="SCALPING",
            confluence_factors=confluence,
        )


def risk_reward(entry: float, sl: float, rr_ratio: float) -> float:
    """Calculate reward distance from entry and SL."""
    return abs(entry - sl) * rr_ratio
