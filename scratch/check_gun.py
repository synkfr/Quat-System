import os
from core.exchange import CoinSwitchExchange

def check_symbol(symbol):
    exchange = CoinSwitchExchange()
    path = "/trade/api/v2/24hr/ticker"
    
    # Check EXCHANGE_2 (Futures)
    try:
        res = exchange._request("GET", path, params={"exchange": "EXCHANGE_2", "symbol": symbol})
        print(f"Futures ({symbol}): {res.get('data', 'Not Found')}")
    except Exception as e:
        print(f"Futures ({symbol}) Error: {e}")
        
    # Check coinswitchx (Spot)
    try:
        res = exchange._request("GET", path, params={"exchange": "coinswitchx", "symbol": symbol})
        print(f"Spot ({symbol}): {res.get('data', 'Not Found')}")
    except Exception as e:
        print(f"Spot ({symbol}) Error: {e}")

if __name__ == "__main__":
    check_symbol("GUN/INR")
    check_symbol("GUM/INR")
    check_symbol("G/INR")
    check_symbol("GUNDAM/INR")
