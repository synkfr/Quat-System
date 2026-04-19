import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple


class Indicators:
    """
    Full technical indicator suite for confluence-based trading.
    All methods are stateless and operate on pandas Series/DataFrames.
    v4.0: Added Stochastic RSI, VWAP, EMA 200, weighted S/R, improved market structure.
    """

    # ── Trend Indicators ────────────────────────────────────

    @staticmethod
    def calculate_ema(data: pd.Series, window: int) -> pd.Series:
        return data.ewm(span=window, adjust=False).mean()

    @staticmethod
    def calculate_sma(data: pd.Series, window: int) -> pd.Series:
        return data.rolling(window=window).mean()

    # ── Momentum Indicators ─────────────────────────────────

    @staticmethod
    def calculate_rsi(data: pd.Series, window: int = 14) -> pd.Series:
        delta = data.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=window).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def calculate_stochastic_rsi(rsi: pd.Series, k_period: int = 14,
                                  d_period: int = 3) -> Dict[str, pd.Series]:
        """
        Stochastic RSI — momentum exhaustion confirmation.
        K = (RSI - RSI_low) / (RSI_high - RSI_low) * 100
        D = SMA(K, d_period)
        """
        rsi_low = rsi.rolling(window=k_period).min()
        rsi_high = rsi.rolling(window=k_period).max()
        rsi_range = rsi_high - rsi_low
        stoch_k = ((rsi - rsi_low) / rsi_range.replace(0, np.nan) * 100).fillna(50.0)
        stoch_d = stoch_k.rolling(window=d_period).mean().fillna(50.0)
        return {"k": stoch_k, "d": stoch_d}

    @staticmethod
    def calculate_macd(data: pd.Series, fast: int = 12, slow: int = 26,
                       signal: int = 9) -> Dict[str, pd.Series]:
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return {
            "macd": macd_line,
            "signal": signal_line,
            "hist": histogram,
        }

    # ── Volatility Indicators ───────────────────────────────

    @staticmethod
    def calculate_bollinger_bands(data: pd.Series, window: int = 20,
                                  num_std: int = 2) -> Dict[str, pd.Series]:
        sma = data.rolling(window=window).mean()
        std = data.rolling(window=window).std()
        return {
            "middle": sma,
            "upper": sma + (std * num_std),
            "lower": sma - (std * num_std),
        }

    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                      window: int = 14) -> pd.Series:
        """Average True Range — used for dynamic SL/TP calculation."""
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(window=window).mean()

    # ── Volume Indicators ───────────────────────────────────

    @staticmethod
    def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        """On-Balance Volume — volume trend confirmation."""
        direction = np.where(close > close.shift(1), 1,
                             np.where(close < close.shift(1), -1, 0))
        obv = (volume * direction).cumsum()
        return pd.Series(obv, index=close.index)

    @staticmethod
    def calculate_volume_sma(volume: pd.Series, window: int = 20) -> pd.Series:
        """Volume moving average for spike detection."""
        return volume.rolling(window=window).mean()

    @staticmethod
    def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series,
                       volume: pd.Series) -> pd.Series:
        """
        Volume Weighted Average Price — intraday fair value.
        VWAP = cumulative(typical_price * volume) / cumulative(volume)
        """
        typical_price = (high + low + close) / 3
        cumulative_tp_vol = (typical_price * volume).cumsum()
        cumulative_vol = volume.cumsum().replace(0, np.nan)
        return cumulative_tp_vol / cumulative_vol

    # ── Trend Strength ──────────────────────────────────────

    @staticmethod
    def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series,
                      window: int = 14) -> Dict[str, pd.Series]:
        """
        Average Directional Index with DI+ and DI- components.
        ADX > 25 = trending, ADX < 20 = ranging.
        Returns dict with 'adx', 'di_plus', 'di_minus' series.
        """
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = true_range.ewm(span=window, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=window, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=window, adjust=False).mean() / atr)

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.ewm(span=window, adjust=False).mean()

        return {
            "adx": adx.fillna(0.0),
            "di_plus": plus_di.fillna(0.0),
            "di_minus": minus_di.fillna(0.0),
        }

    # ── Support & Resistance ────────────────────────────────

    @staticmethod
    def detect_support_resistance(high: pd.Series, low: pd.Series,
                                  close: pd.Series,
                                  lookback: int = 20) -> Dict[str, List[Dict]]:
        """
        Weighted pivot-point based S/R detection.
        Returns levels with touch counts for quality scoring.
        """
        supports = []
        resistances = []

        h = high.values
        l = low.values
        n = len(h)

        window = max(3, lookback // 5)

        for i in range(window, n - window):
            if h[i] == max(h[i - window:i + window + 1]):
                resistances.append(float(h[i]))
            if l[i] == min(l[i - window:i + window + 1]):
                supports.append(float(l[i]))

        # Cluster nearby levels and count touches
        supports = Indicators._cluster_levels_weighted(supports, close)
        resistances = Indicators._cluster_levels_weighted(resistances, close)

        return {"support": supports, "resistance": resistances}

    @staticmethod
    def _cluster_levels_weighted(levels: List[float], close: pd.Series,
                                  threshold: float = 0.005) -> List[Dict]:
        """Merge levels within threshold % and score by touch count."""
        if not levels:
            return []
        levels_sorted = sorted(levels)
        clustered = []
        cluster = [levels_sorted[0]]

        for i in range(1, len(levels_sorted)):
            if abs(levels_sorted[i] - cluster[-1]) / cluster[-1] < threshold:
                cluster.append(levels_sorted[i])
            else:
                mean_level = float(np.mean(cluster))
                clustered.append({"level": mean_level, "touches": len(cluster)})
                cluster = [levels_sorted[i]]
        mean_level = float(np.mean(cluster))
        clustered.append({"level": mean_level, "touches": len(cluster)})

        # Sort by touch count descending (strongest levels first)
        clustered.sort(key=lambda x: x["touches"], reverse=True)
        return clustered[:10]  # Keep top 10 levels

    # ── Market Structure ────────────────────────────────────

    @staticmethod
    def classify_market_structure(close: pd.Series, ema_short: pd.Series,
                                  ema_long: pd.Series,
                                  adx_data: Dict[str, pd.Series]) -> str:
        """
        Classify current market as BULLISH, BEARISH, or RANGING.
        Uses ADX + DI+/DI- for accurate trend classification.
        """
        current_price = close.iloc[-1]
        current_ema_short = ema_short.iloc[-1]
        current_ema_long = ema_long.iloc[-1]
        current_adx = adx_data["adx"].iloc[-1]
        current_di_plus = adx_data["di_plus"].iloc[-1]
        current_di_minus = adx_data["di_minus"].iloc[-1]

        if current_adx < 20:
            return "RANGING"

        # Use DI+/DI- for directional confirmation
        if current_di_plus > current_di_minus and current_price > current_ema_short > current_ema_long:
            return "BULLISH"
        elif current_di_minus > current_di_plus and current_price < current_ema_short < current_ema_long:
            return "BEARISH"
        else:
            return "RANGING"

    # ── Fibonacci Levels ────────────────────────────────────

    @staticmethod
    def calculate_fibonacci_levels(high: float, low: float) -> Dict[str, float]:
        diff = high - low
        return {
            "0.0": high,
            "23.6": high - 0.236 * diff,
            "38.2": high - 0.382 * diff,
            "50.0": high - 0.5 * diff,
            "61.8": high - 0.618 * diff,
            "78.6": high - 0.786 * diff,
            "100.0": low,
        }

    # ── Crossover Detection ─────────────────────────────────

    @staticmethod
    def detect_macd_crossover(macd_data: Dict[str, pd.Series]) -> str:
        """
        Detect actual MACD line / signal line crossover.
        Returns 'BULLISH_CROSS', 'BEARISH_CROSS', or 'NONE'.
        """
        macd = macd_data["macd"]
        signal = macd_data["signal"]

        if len(macd) < 3:
            return "NONE"

        # Current and previous position relative to signal line
        curr_above = macd.iloc[-1] > signal.iloc[-1]
        prev_above = macd.iloc[-2] > signal.iloc[-2]

        if curr_above and not prev_above:
            return "BULLISH_CROSS"
        elif not curr_above and prev_above:
            return "BEARISH_CROSS"
        return "NONE"

    @staticmethod
    def detect_stoch_rsi_crossover(stoch_data: Dict[str, pd.Series]) -> str:
        """
        Detect StochRSI K/D crossover in oversold/overbought zones.
        Returns 'BULLISH_CROSS', 'BEARISH_CROSS', or 'NONE'.
        """
        k = stoch_data["k"]
        d = stoch_data["d"]

        if len(k) < 3:
            return "NONE"

        curr_k = k.iloc[-1]
        prev_k = k.iloc[-2]
        curr_d = d.iloc[-1]
        prev_d = d.iloc[-2]

        # Bullish: K crosses above D in oversold zone (< 30)
        if curr_k > curr_d and prev_k <= prev_d and curr_k < 40:
            return "BULLISH_CROSS"
        # Bearish: K crosses below D in overbought zone (> 70)
        elif curr_k < curr_d and prev_k >= prev_d and curr_k > 60:
            return "BEARISH_CROSS"
        return "NONE"

    # ── Aggregate ───────────────────────────────────────────

    def get_all_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Master method: compute every indicator from a standard OHLCV DataFrame.
        Returns flat dict of latest values + full series for charting.
        """
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df.get("volume", pd.Series(np.ones(len(df)), index=df.index))

        ema_20 = self.calculate_ema(close, 20)
        ema_50 = self.calculate_ema(close, 50)
        ema_200 = self.calculate_ema(close, 200)
        rsi = self.calculate_rsi(close)
        stoch_rsi = self.calculate_stochastic_rsi(rsi)
        macd = self.calculate_macd(close)
        bb = self.calculate_bollinger_bands(close)
        atr = self.calculate_atr(high, low, close)
        obv = self.calculate_obv(close, volume)
        vol_sma = self.calculate_volume_sma(volume)
        vwap = self.calculate_vwap(high, low, close, volume)
        adx_data = self.calculate_adx(high, low, close)
        sr = self.detect_support_resistance(high, low, close)
        structure = self.classify_market_structure(close, ema_20, ema_50, adx_data)
        fib = self.calculate_fibonacci_levels(high.max(), low.min())

        # Crossover detections
        macd_cross = self.detect_macd_crossover(macd)
        stoch_cross = self.detect_stoch_rsi_crossover(stoch_rsi)

        # OBV trend direction (rising or falling over last 5 bars)
        obv_trend = "RISING" if obv.iloc[-1] > obv.iloc[-5] else "FALLING" if len(obv) >= 5 else "FLAT"

        return {
            # Latest scalar values
            "ema_20": ema_20.iloc[-1],
            "ema_50": ema_50.iloc[-1],
            "ema_200": ema_200.iloc[-1],
            "rsi": rsi.iloc[-1],
            "rsi_prev": rsi.iloc[-2] if len(rsi) >= 2 else rsi.iloc[-1],
            "stoch_rsi_k": stoch_rsi["k"].iloc[-1],
            "stoch_rsi_d": stoch_rsi["d"].iloc[-1],
            "macd": macd["macd"].iloc[-1],
            "macd_signal": macd["signal"].iloc[-1],
            "macd_hist": macd["hist"].iloc[-1],
            "macd_crossover": macd_cross,
            "stoch_crossover": stoch_cross,
            "bb_upper": bb["upper"].iloc[-1],
            "bb_middle": bb["middle"].iloc[-1],
            "bb_lower": bb["lower"].iloc[-1],
            "atr": atr.iloc[-1],
            "obv": obv.iloc[-1],
            "obv_trend": obv_trend,
            "volume_sma": vol_sma.iloc[-1],
            "current_volume": volume.iloc[-1],
            "vwap": vwap.iloc[-1],
            "adx": adx_data["adx"].iloc[-1],
            "di_plus": adx_data["di_plus"].iloc[-1],
            "di_minus": adx_data["di_minus"].iloc[-1],
            "market_structure": structure,
            "support_levels": [s["level"] for s in sr["support"]],
            "resistance_levels": [r["level"] for r in sr["resistance"]],
            "support_data": sr["support"],
            "resistance_data": sr["resistance"],
            "fibonacci": fib,
            "close": close.iloc[-1],
            # Full series for charting
            "_series": {
                "ema_20": ema_20,
                "ema_50": ema_50,
                "ema_200": ema_200,
                "rsi": rsi,
                "stoch_rsi": stoch_rsi,
                "macd": macd,
                "bb": bb,
                "atr": atr,
                "obv": obv,
                "vol_sma": vol_sma,
                "vwap": vwap,
                "adx": adx_data,
            },
        }
