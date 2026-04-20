import os
import time
import logging
import requests
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Top 30 cryptocurrencies by market cap, paired with INR
TOP_30_PAIRS = [
    "BTC/INR", "ETH/INR", "BNB/INR", "SOL/INR", "XRP/INR",
    "ADA/INR", "AVAX/INR", "DOT/INR", "MATIC/INR", "LINK/INR",
    "DOGE/INR", "SHIB/INR", "TRX/INR", "UNI/INR", "LTC/INR",
    "ATOM/INR", "ETC/INR", "XLM/INR", "FIL/INR", "NEAR/INR",
    "APT/INR", "ARB/INR", "OP/INR", "ALGO/INR", "ICP/INR",
    "VET/INR", "HBAR/INR", "SAND/INR", "MANA/INR", "GRT/INR",
    "GUN/INR",
]

TOP_30_BASES = [p.split("/")[0] for p in TOP_30_PAIRS]


class AssetFilter:
    """
    Restricts trading to Top 30 crypto assets by market cap.
    v4.0: Added spread check from order book, rank_by_opportunity scoring.
    """

    def __init__(self):
        self.whitelist = set(TOP_30_PAIRS)
        self.bases = set(TOP_30_BASES)
        self.min_volume = float(os.getenv("MIN_VOLUME_THRESHOLD", 10000))
        self._dynamic_whitelist: List[str] = []
        self._whitelist_fetch_time: float = 0
        self._whitelist_ttl: float = 3600 * 6  # Refresh every 6 hours

    def is_allowed(self, symbol: str) -> bool:
        """Check if symbol is in the Top 30 whitelist."""
        symbol_upper = symbol.upper().strip()
        if symbol_upper in self.whitelist:
            return True
        base = symbol_upper.split("/")[0] if "/" in symbol_upper else symbol_upper
        return base in self.bases

    def check_liquidity(self, trades_data: List[Dict[str, Any]],
                        min_volume: float = None) -> Tuple[bool, float, str]:
        """
        Validate liquidity from recent trade data.
        Rejects if total traded volume is below threshold or too few trades.
        Returns: (is_liquid, actual_volume, reason)
        """
        threshold = min_volume or self.min_volume

        if not trades_data:
            return False, 0.0, "No trade data available"

        total_volume = 0.0
        for trade in trades_data:
            qty = float(trade.get("q", trade.get("quantity", 0)))
            price = float(trade.get("p", trade.get("price", 0)))
            total_volume += qty * price

        trade_count = len(trades_data)

        if trade_count < 10:
            return False, total_volume, f"Too few trades ({trade_count}), thin order book"

        if total_volume < threshold:
            return False, total_volume, f"Volume {total_volume:.0f} below threshold {threshold:.0f}"

        # Spread check
        prices = [float(t.get("p", t.get("price", 0))) for t in trades_data
                   if float(t.get("p", t.get("price", 0))) > 0]
        if prices:
            spread = (max(prices) - min(prices)) / min(prices) if min(prices) > 0 else 0
            if spread > 0.05:
                return False, total_volume, f"Spread too wide ({spread:.2%}), slippage risk"

        return True, total_volume, "Liquidity OK"

    def check_spread_from_depth(self, depth_data: Dict[str, Any],
                                 max_spread_pct: float = 0.5) -> Tuple[bool, float]:
        """
        Check bid-ask spread from order book depth.
        Returns (acceptable, spread_pct).
        """
        bids = depth_data.get("bids", [])
        asks = depth_data.get("asks", [])

        if not bids or not asks:
            return True, 0.0  # No data, pass through

        try:
            best_bid = float(bids[0][0]) if isinstance(bids[0], list) else float(bids[0].get("price", 0))
            best_ask = float(asks[0][0]) if isinstance(asks[0], list) else float(asks[0].get("price", 0))

            if best_bid <= 0 or best_ask <= 0:
                return True, 0.0

            spread_pct = (best_ask - best_bid) / best_bid * 100
            return spread_pct <= max_spread_pct, spread_pct
        except (IndexError, ValueError, KeyError):
            return True, 0.0

    def rank_by_opportunity(self, pairs_data: Dict[str, Dict]) -> List[Tuple[str, float]]:
        """
        Score allowed pairs by volatility + volume to auto-select best candidates.
        Returns [(symbol, score), ...] sorted by score descending.
        """
        scores = []
        for symbol, data in pairs_data.items():
            try:
                ticker = data.get("ticker", {})
                high = float(ticker.get("highPrice", 0))
                low = float(ticker.get("lowPrice", 0))
                volume = float(ticker.get("volume", 0))

                if low <= 0 or high <= 0:
                    continue

                # Volatility score: 24h range as percentage
                volatility = (high - low) / low * 100

                # Volume score: normalized (log scale)
                import math
                vol_score = math.log10(max(volume, 1))

                # Combined score (weight volatility higher)
                score = (volatility * 0.6) + (vol_score * 0.4)
                scores.append((symbol, score))
            except (ValueError, TypeError):
                continue

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def get_allowed_pairs(self) -> List[str]:
        """Return the full whitelist for UI dropdown and multi-pair scanning."""
        return sorted(TOP_30_PAIRS)
