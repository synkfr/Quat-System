import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


class Database:
    def __init__(self, db_path: str = "trades.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Trades table (expanded with SL/TP)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    total_value REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    status TEXT NOT NULL,
                    order_id TEXT,
                    ai_reasoning TEXT
                )
            """)

            # AI Signal Logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    reasoning TEXT,
                    raw_response TEXT,
                    market_data_snapshot TEXT
                )
            """)

            # Positions: open and closed with full lifecycle
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_open TEXT NOT NULL,
                    timestamp_close TEXT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    quantity REAL NOT NULL,
                    exit_price REAL,
                    pnl REAL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    confluence_factors TEXT,
                    order_id TEXT
                )
            """)

            # Portfolio snapshots for capital tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    capital REAL NOT NULL,
                    total_pnl REAL NOT NULL DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    loss_count INTEGER DEFAULT 0,
                    max_drawdown REAL DEFAULT 0
                )
            """)

            # System events (news pauses, restarts, etc.)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    description TEXT,
                    duration_minutes INTEGER
                )
            """)

            conn.commit()

    # ── Trades ──────────────────────────────────────────────

    def log_trade(self, symbol: str, side: str, price: float, quantity: float,
                  status: str, order_id: str = None, ai_reasoning: str = None,
                  stop_loss: float = None, take_profit: float = None):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO trades (timestamp, symbol, side, price, quantity,
                    total_value, stop_loss, take_profit, status, order_id, ai_reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(), symbol, side, price, quantity,
                price * quantity, stop_loss, take_profit, status, order_id, ai_reasoning
            ))
            conn.commit()

    def get_trades(self, limit: int = 50) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ── AI Signals ──────────────────────────────────────────

    def log_ai_signal(self, symbol: str, signal: str, reasoning: str,
                      raw_response: str, market_data: Dict):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO ai_signals (timestamp, symbol, signal, reasoning,
                    raw_response, market_data_snapshot)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(), symbol, signal, reasoning,
                raw_response, json.dumps(market_data)
            ))
            conn.commit()

    def get_ai_signals(self, limit: int = 50) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_signals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Positions ───────────────────────────────────────────

    def log_position(self, symbol: str, direction: str, entry_price: float,
                     stop_loss: float, take_profit: float, quantity: float,
                     confluence_factors: List[str] = None, order_id: str = None) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO positions (timestamp_open, symbol, direction, entry_price,
                    stop_loss, take_profit, quantity, status, confluence_factors, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """, (
                datetime.now().isoformat(), symbol, direction, entry_price,
                stop_loss, take_profit, quantity,
                json.dumps(confluence_factors or []), order_id
            ))
            conn.commit()
            return cursor.lastrowid

    def close_position(self, position_id: int, exit_price: float, pnl: float, status: str):
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE positions SET timestamp_close = ?, exit_price = ?,
                    pnl = ?, status = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), exit_price, pnl, status, position_id))
            conn.commit()

    def update_position_sl(self, position_id: int, new_sl: float):
        """Update stop loss for a position (used by trailing stop)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE positions SET stop_loss = ? WHERE id = ?",
                (new_sl, position_id)
            )
            conn.commit()

    def get_open_positions(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status = 'OPEN' ORDER BY timestamp_open DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_position_history(self, limit: int = 100) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status != 'OPEN' ORDER BY timestamp_close DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Portfolio ───────────────────────────────────────────

    def log_portfolio_snapshot(self, capital: float, total_pnl: float,
                               win_count: int, loss_count: int, max_drawdown: float):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO portfolio (timestamp, capital, total_pnl,
                    win_count, loss_count, max_drawdown)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(), capital, total_pnl,
                win_count, loss_count, max_drawdown
            ))
            conn.commit()

    def get_portfolio_history(self, limit: int = 200) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_portfolio(self) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    # ── Win Rate ────────────────────────────────────────────

    def get_win_rate(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(pnl), 0) as total_pnl
                FROM positions WHERE status != 'OPEN'
            """).fetchone()
            # Get latest capital
            cap_row = conn.execute("SELECT capital FROM portfolio ORDER BY timestamp DESC LIMIT 1").fetchone()
            latest_cap = cap_row["capital"] if cap_row else 0.0

            total = row["total"] or 0
            wins = row["wins"] or 0
            return {
                "total": total,
                "wins": wins,
                "losses": row["losses"] or 0,
                "win_rate": (wins / total * 100) if total > 0 else 0.0,
                "total_pnl": row["total_pnl"] or 0.0,
                "capital": latest_cap
            }

    # ── Events ──────────────────────────────────────────────

    def log_event(self, event_type: str, description: str, duration_minutes: int = None):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO events (timestamp, event_type, description, duration_minutes)
                VALUES (?, ?, ?, ?)
            """, (datetime.now().isoformat(), event_type, description, duration_minutes))
            conn.commit()

    def get_events(self, limit: int = 50) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
