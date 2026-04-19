import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional


class PatternRecognition:
    """
    Price action pattern detection for confluence-based trading.
    v5.0: Added Marubozu, Doji detection. Added location-based validation —
    patterns are only valid at S/R levels, Fibonacci zones, or EMA boundaries.
    """

    # ── Engulfing ───────────────────────────────────────────

    @staticmethod
    def detect_engulfing(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detect bullish and bearish engulfing patterns.
        Requires minimum body size > 0.3% of price to filter noise.
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
                        "strength": body_size / c[i] * 100,
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

    # ── Pin Bar ─────────────────────────────────────────────

    @staticmethod
    def detect_pin_bar(df: pd.DataFrame, sr_levels: List[float] = None,
                       wick_ratio: float = 2.0) -> List[Dict[str, Any]]:
        """
        Detect pin bars (hammer / shooting star).
        Pin bars only valid near support/resistance levels.
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

    # ── Marubozu ────────────────────────────────────────────

    @staticmethod
    def detect_marubozu(df: pd.DataFrame, max_wick_pct: float = 0.05) -> List[Dict[str, Any]]:
        """
        Detect Marubozu candles — strong institutional buying/selling.
        A Marubozu has virtually no wicks (< 5% of total range).
        Body must be > 0.5% of price to filter tiny candles.
        """
        signals = []
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values

        for i in range(len(df)):
            total_range = h[i] - l[i]
            if total_range <= 0:
                continue

            body = abs(c[i] - o[i])
            upper_wick = h[i] - max(o[i], c[i])
            lower_wick = min(o[i], c[i]) - l[i]

            # Body must dominate (> 0.5% of price and > 90% of range)
            if c[i] > 0 and (body / c[i]) < 0.005:
                continue
            if body / total_range < 0.90:
                continue

            # Wicks must be tiny
            if upper_wick / total_range > max_wick_pct or lower_wick / total_range > max_wick_pct:
                continue

            direction = "BUY" if c[i] > o[i] else "SELL"
            signals.append({
                "index": i,
                "pattern": f"{'BULLISH' if direction == 'BUY' else 'BEARISH'}_MARUBOZU",
                "direction": direction,
                "price": float(c[i]),
                "strength": body / total_range,  # 0.90-1.0 range
            })

        return signals

    # ── Doji ────────────────────────────────────────────────

    @staticmethod
    def detect_doji(df: pd.DataFrame, body_threshold: float = 0.1) -> List[Dict[str, Any]]:
        """
        Detect Doji candles — indecision / trend exhaustion warning signs.
        A Doji has a very small body (< 10% of total range).
        Classified by wick balance:
          - STANDARD_DOJI: balanced wicks
          - DRAGONFLY_DOJI: long lower wick (bullish reversal potential)
          - GRAVESTONE_DOJI: long upper wick (bearish reversal potential)
        """
        signals = []
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values

        for i in range(len(df)):
            total_range = h[i] - l[i]
            if total_range <= 0:
                continue

            body = abs(c[i] - o[i])
            body_ratio = body / total_range

            if body_ratio > body_threshold:
                continue

            upper_wick = h[i] - max(o[i], c[i])
            lower_wick = min(o[i], c[i]) - l[i]

            # Classify doji type
            if lower_wick > 2 * upper_wick and lower_wick > 0.3 * total_range:
                pattern = "DRAGONFLY_DOJI"
                direction = "BUY"  # Potential bullish reversal
            elif upper_wick > 2 * lower_wick and upper_wick > 0.3 * total_range:
                pattern = "GRAVESTONE_DOJI"
                direction = "SELL"  # Potential bearish reversal
            else:
                pattern = "STANDARD_DOJI"
                direction = "NEUTRAL"

            signals.append({
                "index": i,
                "pattern": pattern,
                "direction": direction,
                "price": float(c[i]),
                "strength": 1.0 - body_ratio,  # Higher = more doji-like
            })

        return signals

    # ── Breakout-Retest ─────────────────────────────────────

    @staticmethod
    def detect_breakout_retest(df: pd.DataFrame, sr_levels: List[float],
                               tolerance: float = 0.002) -> List[Dict[str, Any]]:
        """
        Detect breakout-retest setups.
        Requires volume surge on breakout candle (volume > 1.5x SMA).
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

    # ── Liquidity Grab ──────────────────────────────────────

    @staticmethod
    def detect_liquidity_grab(df: pd.DataFrame, sr_levels: List[float],
                              tolerance: float = 0.003) -> List[Dict[str, Any]]:
        """
        Detect liquidity grabs / stop hunts.
        Requires reversal candle close beyond midpoint of wick (strong rejection).
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

    # ── Location Validator ──────────────────────────────────

    @staticmethod
    def validate_location(pattern: Dict[str, Any],
                          sr_levels: List[float],
                          fib_levels: Dict[str, float],
                          ema_values: Dict[str, float],
                          current_volume: float = 0,
                          avg_volume: float = 0,
                          proximity_pct: float = 1.5) -> Dict[str, Any]:
        """
        Location-based validity filter. A pattern is ONLY a valid entry trigger
        if it occurs at a confirmed technical zone:
          1. Support/Resistance level (within proximity_pct%)
          2. Fibonacci retracement zone (38.2%, 50%, 61.8%)
          3. EMA boundary (EMA 20, 50, or 200)

        Also checks for volume confirmation (above average).

        Returns the pattern dict with added fields:
          - location_valid: bool
          - location_factors: list of reasons
          - location_score: float (0-1, higher = better location)
        """
        price = pattern.get("price", 0)
        if price <= 0:
            pattern["location_valid"] = False
            pattern["location_factors"] = []
            pattern["location_score"] = 0.0
            return pattern

        factors = []
        score = 0.0

        # 1. S/R proximity
        if sr_levels:
            for level in sr_levels:
                if level > 0:
                    pct_dist = abs(price - level) / level * 100
                    if pct_dist <= proximity_pct:
                        factors.append(f"S/R level {level:.0f} ({pct_dist:.1f}%)")
                        score += 0.35
                        break

        # 2. Fibonacci zones (38.2%, 50%, 61.8% — the golden trio)
        if fib_levels:
            fib_keys = ["fib_382", "fib_500", "fib_618"]
            fib_names = ["38.2%", "50%", "61.8%"]
            for fk, fn in zip(fib_keys, fib_names):
                fib_val = fib_levels.get(fk, 0)
                if fib_val > 0:
                    pct_dist = abs(price - fib_val) / fib_val * 100
                    if pct_dist <= proximity_pct:
                        factors.append(f"Fib {fn} ({fib_val:.0f})")
                        score += 0.30
                        break

        # 3. EMA boundary (within 0.5% of EMA 20, 50, or 200)
        ema_proximity = 0.5
        for ema_name, ema_val in ema_values.items():
            if ema_val and ema_val > 0:
                pct_dist = abs(price - ema_val) / ema_val * 100
                if pct_dist <= ema_proximity:
                    factors.append(f"{ema_name} ({ema_val:.0f})")
                    score += 0.20
                    break

        # 4. Volume confirmation (bonus)
        if current_volume > 0 and avg_volume > 0:
            if current_volume > 1.2 * avg_volume:
                factors.append(f"Volume {current_volume/avg_volume:.1f}x avg")
                score += 0.15

        pattern["location_valid"] = len(factors) > 0
        pattern["location_factors"] = factors
        pattern["location_score"] = min(score, 1.0)
        return pattern

    # ── Master Scanner ──────────────────────────────────────

    def scan_all(self, df: pd.DataFrame,
                 sr_levels: List[float] = None,
                 fib_levels: Dict[str, float] = None,
                 ema_values: Dict[str, float] = None,
                 current_volume: float = 0,
                 avg_volume: float = 0) -> List[Dict[str, Any]]:
        """
        Run all pattern detectors on the DataFrame.
        Returns merged list sorted by strength (highest quality first).
        Only returns patterns from the last 5 candles (recent signals only).

        v5.0: All reversal/momentum patterns are validated for location.
        Patterns in the "middle of nowhere" are filtered out.
        Doji patterns are returned as warnings (not entry triggers).
        """
        all_signals = []
        all_signals.extend(self.detect_engulfing(df))
        all_signals.extend(self.detect_pin_bar(df, sr_levels))
        all_signals.extend(self.detect_marubozu(df))

        if sr_levels:
            all_signals.extend(self.detect_breakout_retest(df, sr_levels))
            all_signals.extend(self.detect_liquidity_grab(df, sr_levels))

        # Filter to only recent patterns (last 5 candles)
        cutoff = len(df) - 5
        recent = [s for s in all_signals if s["index"] >= cutoff]

        # Apply location validation to reversal/momentum patterns
        location_patterns = {"BULLISH_ENGULFING", "BEARISH_ENGULFING",
                             "BULLISH_PIN_BAR", "BEARISH_PIN_BAR",
                             "BULLISH_MARUBOZU", "BEARISH_MARUBOZU"}

        validated = []
        for sig in recent:
            if sig["pattern"] in location_patterns:
                sig = self.validate_location(
                    sig,
                    sr_levels=sr_levels or [],
                    fib_levels=fib_levels or {},
                    ema_values=ema_values or {},
                    current_volume=current_volume,
                    avg_volume=avg_volume,
                )
                # Only keep patterns at valid locations
                if sig.get("location_valid", False):
                    validated.append(sig)
            else:
                # Breakout/retest and liquidity grabs are already at S/R by definition
                validated.append(sig)

        # Doji as warnings (separate scan, not entry triggers)
        doji_signals = self.detect_doji(df)
        recent_doji = [s for s in doji_signals if s["index"] >= cutoff]
        for d in recent_doji:
            d["is_warning"] = True
            validated.append(d)

        # Sort by strength descending (highest quality first)
        validated.sort(key=lambda x: x.get("strength", 0), reverse=True)
        return validated
