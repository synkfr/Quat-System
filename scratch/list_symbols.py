import os
from core.exchange import CoinSwitchExchange

def list_symbols():
    exchange = CoinSwitchExchange()
    # Path for ticker to get all symbols
    path = "/trade/api/v2/24hr/ticker"
    # Exchange EXCHANGE_2 is often used for futures
    res = exchange._request("GET", path, params={"exchange": "EXCHANGE_2"})
    data = res.get("data", {})
    if isinstance(data, dict) and "EXCHANGE_2" in data:
        symbols = list(data["EXCHANGE_2"].keys())
        print(f"EXCHANGE_2 Symbols: {symbols}")
    
    # Also check coinswitchx (spot)
    res_spot = exchange._request("GET", path, params={"exchange": "coinswitchx"})
    data_spot = res_spot.get("data", {})
    if isinstance(data_spot, dict) and "coinswitchx" in data_spot:
        symbols_spot = list(data_spot["coinswitchx"].keys())
        print(f"Spot Symbols: {symbols_spot}")

if __name__ == "__main__":
    list_symbols()
