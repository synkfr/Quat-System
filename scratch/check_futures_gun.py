import os
from core.exchange import CoinSwitchExchange

def check_futures_symbol(symbol):
    exchange = CoinSwitchExchange()
    path = "/trade/api/v2/24hr/ticker"
    try:
        res = exchange._request("GET", path, params={"exchange": "EXCHANGE_2", "symbol": symbol})
        print(f"Futures ({symbol}): {res.get('data', 'Not Found')}")
    except Exception as e:
        print(f"Futures ({symbol}) Error: {e}")

if __name__ == "__main__":
    check_futures_symbol("gunusdt")
    check_futures_symbol("GUNDAMUSDT")
    check_futures_symbol("gun/usdt")
