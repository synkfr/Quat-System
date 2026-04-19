import requests
import json
import time
import urllib.parse
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
import os
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()


class CoinSwitchExchange:
    """
    CoinSwitch Pro API client for live execution.
    Handles authentication and order management.
    """

    def __init__(self):
        self.api_key = os.getenv("COIN_SWITCH_API_KEY")
        self.secret_key = os.getenv("COIN_SWITCH_SECRET_KEY")
        self.base_url = "https://coinswitch.co"

    # ── Authentication ──────────────────────────────────────

    def _generate_signature(self, method: str, url_path: str,
                            body_dict: Dict[str, Any], epoch_time: str) -> str:
        body_str = json.dumps(body_dict, separators=(",", ":"), sort_keys=True) if body_dict else ""
        unquoted_path = urllib.parse.unquote(url_path)
        message = method.upper() + unquoted_path + body_str + epoch_time

        private_key_bytes = bytes.fromhex(self.secret_key)
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        signature = private_key.sign(message.encode("utf-8"))
        return signature.hex()

    def _request(self, method: str, path: str, params: Optional[Dict] = None,
                 body: Optional[Dict] = None) -> Dict:
        if body is None:
            body = {}

        epoch_time = str(int(time.time() * 1000))

        url_path = path
        if params:
            # Sort params for signature alignment (CoinSwitch requires alphabetical sorting)
            sorted_params = sorted(params.items())
            query_string = urllib.parse.urlencode(sorted_params)
            url_path = f"{path}?{query_string}"

        signature = self._generate_signature(method, url_path, body, epoch_time)

        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.api_key,
            "X-AUTH-SIGNATURE": signature,
            "X-AUTH-EPOCH": epoch_time,
        }

        url = f"{self.base_url}{url_path}"

        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=15)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=body, timeout=15)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, json=body, timeout=15)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if response.status_code != 200:
            raise Exception(f"API Request failed: {response.status_code} - {response.text}")

        return response.json()

    # ── Market Data ─────────────────────────────────────────

    def get_ticker(self, symbol: str, exchange: str = "coinswitchx") -> Dict[str, Any]:
        """Fetch 24h ticker. Returns flattened data dict with standard keys."""
        path = "/trade/api/v2/24hr/ticker"
        params = {"symbol": symbol, "exchange": exchange}
        raw = self._request("GET", path, params=params)
        return {"data": self._flatten_ticker(raw, exchange)}

    @staticmethod
    def _flatten_ticker(raw: Dict, exchange: str = "coinswitchx") -> Dict[str, Any]:
        """CoinSwitch nests ticker data under data.<exchange>. Flatten it."""
        data = raw.get("data", {})
        # Handle nested format: {"data": {"coinswitchx": {...}}}
        if isinstance(data, dict) and exchange in data:
            data = data[exchange]
        return data

    def get_recent_trades(self, symbol: str, exchange: str = "coinswitchx",
                          limit: int = 100) -> Dict[str, Any]:
        path = "/trade/api/v2/trades"
        params = {"symbol": symbol, "exchange": exchange, "limit": limit}
        return self._request("GET", path, params=params)

    def get_candles(self, symbol: str, interval: str, start_time: int = None, end_time: int = None,
                    limit: int = 1000, exchange: str = "coinswitchx") -> List[list]:
        """Fetch historical klines/candles."""
        path = "/trade/api/v2/candles"
        
        # Calculate timestamps if not provided
        if not end_time:
            end_time = int(time.time() * 1000)
            
        # Parse interval to minutes and ms
        multiplier = int(''.join(filter(str.isdigit, interval)) or 1)
        if 'm' in interval.lower():
            minutes = multiplier
        elif 'h' in interval.lower():
            minutes = multiplier * 60
        elif 'd' in interval.lower():
            minutes = multiplier * 24 * 60
        else:
            # Fallback assuming already in minutes
            minutes = int(interval) if str(interval).isdigit() else 1

        ms_per_candle = minutes * 60 * 1000
            
        if not start_time:
            start_time = end_time - (ms_per_candle * limit)

        params = {
            "symbol": symbol, 
            "exchange": exchange, 
            "interval": str(minutes), # API expects minutes as string (e.g. "15", "60", "240")
            "limit": limit,
            "start_time": start_time,
            "end_time": end_time
        }

        try:
            res = self._request("GET", path, params=params)
            return res.get("data", [])
        except Exception as e:
            import logging
            logger = logging.getLogger("QuatBot")
            logger.error(f"Failed to fetch candles: {e}")
            return []

    def get_depth(self, symbol: str, exchange: str = "coinswitchx") -> Dict[str, Any]:
        """Fetch active Order Book depth."""
        path = "/trade/api/v2/depth"
        params = {"symbol": symbol, "exchange": exchange}
        try:
            res = self._request("GET", path, params=params)
            return res.get("data", {})
        except Exception:
            return {}

    def ping(self) -> bool:
        path = "/trade/api/v2/ping"
        try:
            res = self._request("GET", path)
            # CoinSwitch ping returns {"message": "OK"}
            return res.get("message") == "OK" or res.get("status") == "success"
        except Exception:
            return False

    # ── User & Portfolio ────────────────────────────────────

    def get_portfolio(self, exchange: str = "coinswitchx") -> Dict[str, Any]:
        """Fetch real user balances."""
        path = "/trade/api/v2/user/portfolio"
        params = {"exchange": exchange}
        try:
            return self._request("GET", path, params=params)
        except Exception as e:
            return {}

    # ── Order Management ────────────────────────────────────

    def place_order(self, symbol: str, side: str, order_type: str,
                    price: float, quantity: float,
                    exchange: str = "coinswitchx") -> Dict[str, Any]:
        """Place a live order."""
        path = "/trade/api/v2/order"
        body = {
            "symbol": symbol,
            "side": side.lower(),
            "type": order_type.lower(),
            "price": float(price),
            "quantity": float(quantity),
            "exchange": exchange,
        }
        return self._request("POST", path, body=body)

    def get_order_status(self, order_id: str,
                         exchange: str = "coinswitchx") -> Dict[str, Any]:
        """Check status of an existing order."""
        path = "/trade/api/v2/order"
        params = {"order_id": order_id, "exchange": exchange}
        return self._request("GET", path, params=params)

    def cancel_order(self, order_id: str,
                     exchange: str = "coinswitchx") -> Dict[str, Any]:
        """Cancel a pending order."""
        path = "/trade/api/v2/order"
        body = {"order_id": order_id, "exchange": exchange}
        return self._request("DELETE", path, body=body)

    def get_open_orders(self, symbol: str = None,
                        exchange: str = "coinswitchx") -> List[Dict]:
        """List active orders."""
        path = "/trade/api/v2/orders"
        params = {"exchange": exchange}
        if symbol:
            params["symbol"] = symbol
        try:
            res = self._request("GET", path, params=params)
            return res.get("data", [])
        except Exception:
            return []

    def check_sl_tp_hit(self, position: Dict, current_price: float) -> Optional[str]:
        """
        Check if current price hits SL or TP for a position.
        Returns: 'SL', 'TP', or None
        """
        sl = position.get("stop_loss", 0)
        tp = position.get("take_profit", 0)
        direction = position.get("direction", "BUY")

        if direction == "BUY":
            if current_price <= sl:
                return "SL"
            if current_price >= tp:
                return "TP"
        else:  # SELL
            if current_price >= sl:
                return "SL"
            if current_price <= tp:
                return "TP"

        return None
