import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Any

class DataProcessor:
    @staticmethod
    def trades_to_ohlcv(trades_data: List[Dict[str, Any]], interval: str = '1Min') -> pd.DataFrame:
        """
        Aggregates raw trade snapshots into OHLCV candles.
        Expected trade format: {'E': timestamp_ms, 'p': price, 'q': quantity, ...}
        """
        if not trades_data:
            return pd.DataFrame()

        df = pd.DataFrame(trades_data)
        
        # Standardize column names
        # CoinSwitch V2 uses 'E' or 't' for timestamp, 'p' for price, 'q' for quantity
        df['timestamp'] = pd.to_datetime(df['E'], unit='ms')
        df['price'] = df['p'].astype(float)
        df['quantity'] = df['q'].astype(float)
        
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        # Resample into OHLCV buckets
        ohlcv = df['price'].resample(interval).ohlc()
        volume = df['quantity'].resample(interval).sum()
        
        result = pd.concat([ohlcv, volume], axis=1)
        result.columns = ['open', 'high', 'low', 'close', 'volume']
        
        # Handle gaps (ffill close, then set open/high/low to close)
        result['close'] = result['close'].ffill()
        result['open'] = result['open'].fillna(result['close'])
        result['high'] = result['high'].fillna(result['close'])
        result['low'] = result['low'].fillna(result['close'])
        result['volume'] = result['volume'].fillna(0)
        
        # Reset index to have timestamp as a column for Plotly
        result.reset_index(inplace=True)
        return result

    @staticmethod
    def format_native_candles(raw_candles: List[dict]) -> pd.DataFrame:
        """
        Converts CoinSwitch Pro native /v2/candles array of dictionaries into our standard DataFrame.
        """
        if not raw_candles:
            return pd.DataFrame()

        # The API returns list of dicts with keys: 'start_time', 'o', 'h', 'l', 'c', 'volume'
        df = pd.DataFrame(raw_candles)

        df.rename(columns={
            "start_time": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close"
        }, inplace=True)

        df['timestamp'] = pd.to_datetime(pd.to_numeric(df['timestamp']), unit='ms')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)

        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        return df
