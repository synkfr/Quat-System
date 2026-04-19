import pandas as pd
import numpy as np
from typing import List, Dict, Any


class PatternRecognition:
    """
    Price action pattern detection for confluence-based trading.
    v4.0: Added quality filters — body size, S/R proximity, volume confirmation.
    """

    @staticmethod
    def detect_engulfing(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detect bullish and bearish engulfing patterns.
        v4.0: Requires minimum body size > 0.3% of price to filter noise.
        """
        signals = []
        o = df["open"].values
        c = df["close"].values

        for i in range(1, len(df)):
            prev_body_top = max(o[i - 1], c[i - 1])
            prev_body_bot = min(o[i - 1], c[i - 1])
            curr_body_top = max(o[i], c[i])
            curr_body_bot = min(o[i], c[i])

            # Body size filter: current candle body must be > 0.3% of price
            body_size = abs(c[i] - o[i])
            if c[i] > 0 and (body_size / c[i]) < 0.003:
                continue

            prev_bearish = c[i - 1] < o[i - 1]
            prev_bullish = c[i - 1] > o[i - 1]
            curr_bullish = c[i] > o[i]
            curr_bearish = c[i] < o[i]

            # Bullish engulfing
            if prev_bearish and curr_bullish:
                if curr_body_bot <= prev_body_bot and curr_body_top >= prev_body_top:
                    signals.append({
                        "index": i,
                        "pattern": "BULLISH_ENGULFING",
                        "direction": "BUY",
                        "price": float(c[i]),
                        "strength": body_size / c[i] * 100,  # Relative body size
                    })

            # Bearish engulfing
            if prev_bullish and curr_bearish:
                if curr_body_bot <= prev_body_bot and curr_body_top >= prev_body_top:
                    signals.append({
                        "index": i,
                        "pattern": "BEARISH_ENGULFING",
                        "direction": "SELL",
                        "price": float(c[i]),
                        "strength": body_size / c[i] * 100,
                    })

        return signals

    @staticmethod
    def detect_pin_bar(df: pd.DataFrame, sr_levels: List[float] = None,
                       wick_ratio: float = 2.0) -> List[Dict[str, Any]]:
        """
        Detect pin bars (hammer / shooting star).
        v4.0: Pin bars only valid near support/resistance levels.
        """
        signals = []
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values

        for i in range(len(df)):
            body = abs(c[i] - o[i])
            if body < 1e-10:
                continue

            upper_wick = h[i] - max(o[i], c[i])
            lower_wick = min(o[i], c[i]) - l[i]

            # S/R proximity check (within 1% of any level)
            near_sr = True  # Default to true if no levels provided
            if sr_levels:
                near_sr = any(
                    abs(c[i] - level) / level < 0.01
                    for level in sr_levels if level > 0
                )

            # Bullish pin bar (hammer): long lower wick, small upper wick
            if lower_wick >= wick_ratio * body and upper_wick < body and near_sr:
                signals.append({
                    "index": i,
                    "pattern": "BULLISH_PIN_BAR",
                    "direction": "BUY",
                    "price": float(c[i]),
                    "strength": lower_wick / body,
                })

            # Bearish pin bar (shooting star): long upper wick, small lower wick
            if upper_wick >= wick_ratio * body and lower_wick < body and near_sr:
                signals.append({
                    "index": i,
                    "pattern": "BEARISH_PIN_BAR",
                    "direction": "SELL",
                    "price": float(c[i]),
                    "strength": upper_wick / body,
                })

        return signals

    @staticmethod
    def detect_breakout_retest(df: pd.DataFrame, sr_levels: List[float],
                               tolerance: float = 0.002) -> List[Dict[str, Any]]:
        """
        Detect breakout-retest setups.
        v4.0: Requires volume surge on breakout candle (volume > 1.5x SMA).
        """
        signals = []
        if len(df) < 10 or not sr_levels:
            return signals

        c = df["close"].values
        h = df["high"].values
        l = df["low"].values
        v = df["volume"].values if "volume" in df.columns else None
        vol_sma = df["volume"].rolling(20).mean().values if v is not None else None

        for level in sr_levels:
            for i in range(max(3, len(df) - 10), len(df)):
                if i < 2:
                    continue

                # Volume confirmation on the breakout candle (i-1)
                volume_confirmed = True
                if v is not None and vol_sma is not None and not pd.isna(vol_sma[i - 1]):
                    if vol_sma[i - 1] > 0:
                        volume_confirmed = v[i - 1] > 1.5 * vol_sma[i - 1]

                if not volume_confirmed:
                    continue

                # Bullish breakout-retest
                was_below = c[i - 2] < level
                broke_above = c[i - 1] > level * (1 + tolerance)
                retested = abs(l[i] - level) / level < tolerance
                continued_up = c[i] > level * (1 + tolerance)

                if was_below and broke_above and retested and continued_up:
                    signals.append({
                        "index": i,
                        "pattern": "BREAKOUT_RETEST_BULL",
                        "direction": "BUY",
                        "price": float(c[i]),
                        "level": level,
                        "strength": 1.0,
                    })

                # Bearish breakout-retest
                was_above = c[i - 2] > level
                broke_below = c[i - 1] < level * (1 - tolerance)
                retested_r = abs(h[i] - level) / level < tolerance
                continued_down = c[i] < level * (1 - tolerance)

                if was_above and broke_below and retested_r and continued_down:
                    signals.append({
                        "index": i,
                        "pattern": "BREAKOUT_RETEST_BEAR",
                        "direction": "SELL",
                        "price": float(c[i]),
                        "level": level,
                        "strength": 1.0,
                    })

        return signals

    @staticmethod
    def detect_liquidity_grab(df: pd.DataFrame, sr_levels: List[float],
                              tolerance: float = 0.003) -> List[Dict[str, Any]]:
        """
        Detect liquidity grabs / stop hunts.
        v4.0: Requires reversal candle close beyond midpoint of wick (strong rejection).
        """
        signals = []
        if len(df) < 2 or not sr_levels:
            return signals

        c = df["close"].values
        h = df["high"].values
        l = df["low"].values
        o = df["open"].values

        for level in sr_levels:
            for i in range(1, len(df)):
                # Bullish liquidity grab at support
                if l[i] < level * (1 - tolerance) and c[i] > level and o[i] > level:
                    if c[i] > o[i]:
                        # v4.0: Close must be above midpoint of candle range
                        candle_mid = (h[i] + l[i]) / 2
                        if c[i] > candle_mid:
                            signals.append({
                                "index": i,
                                "pattern": "LIQUIDITY_GRAB_BULL",
                                "direction": "BUY",
                                "price": float(c[i]),
                                "level": level,
                                "strength": (c[i] - l[i]) / (h[i] - l[i]) if h[i] != l[i] else 0,
                            })

                # Bearish liquidity grab at resistance
                if h[i] > level * (1 + tolerance) and c[i] < level and o[i] < level:
                    if c[i] < o[i]:
                        candle_mid = (h[i] + l[i]) / 2
                        if c[i] < candle_mid:
                            signals.append({
                                "index": i,
                                "pattern": "LIQUIDITY_GRAB_BEAR",
                                "direction": "SELL",
                                "price": float(c[i]),
                                "level": level,
                                "strength": (h[i] - c[i]) / (h[i] - l[i]) if h[i] != l[i] else 0,
                            })

        return signals

    def scan_all(self, df: pd.DataFrame,
                 sr_levels: List[float] = None) -> List[Dict[str, Any]]:
        """
        Run all pattern detectors on the DataFrame.
        Returns merged list sorted by strength (highest quality first).
        Only returns patterns from the last 5 candles (recent signals only).
        """
        all_signals = []
        all_signals.extend(self.detect_engulfing(df))
        all_signals.extend(self.detect_pin_bar(df, sr_levels))

        if sr_levels:
            all_signals.extend(self.detect_breakout_retest(df, sr_levels))
            all_signals.extend(self.detect_liquidity_grab(df, sr_levels))

        # Filter to only recent patterns (last 5 candles)
        cutoff = len(df) - 5
        recent = [s for s in all_signals if s["index"] >= cutoff]
        # Sort by strength descending (highest quality first)
        recent.sort(key=lambda x: x.get("strength", 0), reverse=True)
        return recent
