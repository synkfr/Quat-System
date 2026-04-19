import time
import logging
import json
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv

from core.exchange import CoinSwitchExchange
from core.ai_engine import AIEngine
from core.indicators import Indicators
from core.signal_engine import SignalEngine
from core.risk_manager import RiskManager
from core.asset_filter import AssetFilter
from core.news_filter import NewsFilter
from core.session_filter import SessionFilter
from core.regime_detector import RegimeDetector
from core.notifier import EmailNotifier
from core.data_processor import DataProcessor
from database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("QuatBot")

os.makedirs("logs", exist_ok=True)
fh = logging.FileHandler("logs/bot.log")
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(fh)


class QuatBot:
    """
    v5.0 Trading Pipeline:
    1. News filter (macro event kill-switch)
    2. Session filter (London/NY only for new entries)
    3. Daily loss limit check
    4. Multi-pair data fetch + candle build
    5. Liquidity + spread check per pair
    6. Regime detection per pair
    7. Strategy dispatch per regime
    8. Post-filters (MTFA, EMA200, volume)
    9. AI confirmation (veto gate)
    10. Risk validation (position limits, cooldown)
    11. Execute best 3-5 signals
    12. Monitor all open positions (trailing stop + SL/TP — ALWAYS active)
    """

    def __init__(self):
        self.exchange = CoinSwitchExchange()
        self.ai = AIEngine()
        self.db = Database()
        self.indicators = Indicators()
        self.signal_engine = SignalEngine()
        self.risk_manager = RiskManager()
        self.asset_filter = AssetFilter()
        self.news_filter = NewsFilter()
        self.session_filter = SessionFilter()
        self.notifier = EmailNotifier()
        self.processor = DataProcessor()

        self.symbol = os.getenv("DEFAULT_TRADING_PAIR", "BTC/INR")
        self.trading_interval = int(os.getenv("TRADING_INTERVAL_MINUTES", 1))
        self.paper_trading = os.getenv("PAPER_TRADING", "true").lower() == "true"
        self.multi_pair_scan = os.getenv("MULTI_PAIR_SCAN", "true").lower() == "true"
        self.max_signals_per_cycle = int(os.getenv("MAX_SIGNALS_PER_CYCLE", 3))
        self.spread_max_pct = float(os.getenv("MAX_SPREAD_PCT", 0.5))
        self._was_paused = False

    def _update_status(self, step: str, action: str, details: str, is_sleeping: bool = False,
                        extra: dict = None):
        try:
            status = {
                "timestamp": datetime.now().isoformat(),
                "symbol": getattr(self, "symbol", "UNKNOWN"),
                "step": step,
                "action": action,
                "details": details,
                "is_sleeping": is_sleeping,
            }
            if extra:
                status.update(extra)
            with open(".bot_status.json", "w") as f:
                json.dump(status, f)
        except Exception:
            pass

    def run_iteration(self) -> dict:
        """Single iteration of the v5.0 pipeline."""
        self._update_status("INIT", "STARTED", "Pipeline starting...")
        status = {"timestamp": datetime.now().isoformat(), "step": "INIT",
                  "action": "NONE", "details": ""}

        try:
            self.risk_manager.tick_cooldown()

            # Step 1: News filter
            safe, reason = self.news_filter.is_trading_safe()
            if not safe:
                self._update_status("NEWS", "PAUSED", reason)
                logger.warning(f"NEWS PAUSE: {reason}")
                if not self._was_paused:
                    self.db.log_event("NEWS_PAUSE", reason)
                    self.notifier.send_system_pause(reason)
                    self._was_paused = True
                # ALWAYS monitor positions even when paused
                self._monitor_all_positions()
                return {"step": "NEWS", "action": "PAUSED", "details": reason}

            if self._was_paused:
                self._was_paused = False
                self.db.log_event("RESUME", "Trading resumed")
                self.notifier.send_system_resume()

            # Step 2: Session filter
            can_trade, session_name = self.session_filter.can_open_new_trade()
            if not can_trade:
                self._update_status("SESSION", "BLOCKED", f"No new trades: {session_name}")
                logger.info(f"SESSION BLOCK: {session_name} — monitoring positions only")
                self._sync_portfolio()
                # ALWAYS monitor positions (can close during Asian session)
                self._monitor_all_positions()
                return {"step": "SESSION", "action": "BLOCKED", "details": session_name}
            else:
                logger.info(f"Session: {session_name}")

            # Step 3: Daily loss limit
            daily_hit, daily_reason = self.risk_manager.check_daily_limit()
            if daily_hit:
                self._update_status("RISK", "DAILY_LIMIT", daily_reason)
                logger.warning(f"DAILY LIMIT: {daily_reason}")
                self._monitor_all_positions()
                return {"step": "RISK", "action": "DAILY_LIMIT", "details": daily_reason}

            # Step 3.5: Sync portfolio
            self._sync_portfolio()

            # Step 4: Build scan list
            scan_pairs = self.asset_filter.get_allowed_pairs() if self.multi_pair_scan else [self.symbol]
            logger.info(f"Scanning {len(scan_pairs)} pairs [{session_name}]")

            # Step 5: Fetch data + liquidity + spread checks
            self._update_status("DATA", "FETCHING", f"Building data for {len(scan_pairs)} pairs...")
            pairs_data = {}
            current_prices = {}
            regime_info = {}

            for pair in scan_pairs:
                try:
                    # Quick ticker check
                    ticker_res = self.exchange.get_ticker(pair)
                    ticker = ticker_res.get("data", {})
                    price = float(ticker.get("lastPrice", 0))
                    if price <= 0:
                        continue
                    current_prices[pair] = price

                    # Spread filter (from order book depth)
                    depth = self.exchange.get_depth(pair)
                    if depth:
                        spread_ok, spread_pct = self.asset_filter.check_spread_from_depth(
                            depth, max_spread_pct=self.spread_max_pct
                        )
                        if not spread_ok:
                            logger.debug(f"SKIP {pair}: Spread {spread_pct:.2f}% > {self.spread_max_pct}%")
                            continue

                    # Liquidity check
                    trades_res = self.exchange.get_recent_trades(pair, limit=500)
                    raw_trades = trades_res.get("data", [])
                    is_liquid, volume, liq_reason = self.asset_filter.check_liquidity(raw_trades)
                    if not is_liquid:
                        logger.debug(f"SKIP {pair}: {liq_reason}")
                        continue

                    # Fetch multi-timeframe candles
                    raw_15m = self.exchange.get_candles(pair, interval="15m", limit=100)
                    raw_1h = self.exchange.get_candles(pair, interval="1h", limit=100)
                    raw_4h = self.exchange.get_candles(pair, interval="4h", limit=100)

                    df_15m = self.processor.format_native_candles(raw_15m)
                    df_1h = self.processor.format_native_candles(raw_1h)
                    df_4h = self.processor.format_native_candles(raw_4h)

                    if df_15m.empty or len(df_15m) < 30:
                        continue

                    pairs_data[pair] = {"15m": df_15m, "1h": df_1h, "4h": df_4h}

                except Exception as e:
                    logger.debug(f"Data fetch failed for {pair}: {e}")
                    continue

            if not pairs_data:
                self._update_status("DATA", "NO_DATA", "No valid data")
                self._monitor_all_positions()
                return {"step": "DATA", "action": "NO_DATA", "details": "No valid pairs"}

            logger.info(f"Data ready for {len(pairs_data)} pairs")

            # Step 6-8: Signal engine (regime detection + strategy dispatch + post-filters)
            self._update_status("SIGNAL", "ANALYZING", f"Regime detection + strategy dispatch...")

            signals = self.signal_engine.scan_multiple_pairs(
                pairs_data, max_signals=self.max_signals_per_cycle
            )

            if not signals:
                # Log regime info for debugging
                regime_summary = []
                for pair, data in list(pairs_data.items())[:5]:
                    try:
                        ind = self.indicators.get_all_indicators(data["15m"])
                        det = self.signal_engine._get_detector(pair)
                        regime = det.detect(data["15m"], ind)
                        regime_summary.append(f"{pair.split('/')[0]}:{regime.value[:4]}")
                    except Exception:
                        pass

                regime_str = " | ".join(regime_summary) if regime_summary else "N/A"
                self._update_status("SIGNAL", "HOLD",
                                    f"No signals ({len(pairs_data)} pairs) | Regimes: {regime_str}")
                logger.info(f"HOLD: No signals | Regimes: {regime_str}")
                self._monitor_all_positions()
                return {"step": "SIGNAL", "action": "HOLD",
                        "details": f"Regimes: {regime_str}"}

            logger.info(f"SIGNALS FOUND: {len(signals)}")
            for sig in signals:
                logger.info(
                    f"  {sig.symbol} {sig.direction} [{sig.strategy}] "
                    f"Regime={sig.regime} Conf={sig.confidence:.2f} "
                    f"Gates={sig.gate_results}"
                )

            # Step 9-11: Process signals through AI + Risk + Execute
            executed = 0
            for signal in signals:
                result = self._process_signal(signal, current_prices.get(signal.symbol, 0))
                if result:
                    executed += 1

            action = f"EXECUTED_{executed}" if executed > 0 else "VETOED"
            details = f"{executed}/{len(signals)} signals executed" if executed > 0 \
                else f"All {len(signals)} signals filtered by AI/Risk"

            self._update_status("EXEC", action, details)

            # Step 12: Monitor positions
            self._monitor_all_positions()

            return {"step": "EXEC", "action": action, "details": details}

        except Exception as e:
            logger.error(f"Iteration failed: {e}", exc_info=True)
            self._monitor_all_positions()  # Always try to monitor
            return {"step": "ERROR", "action": "ERROR", "details": str(e)}

    def _process_signal(self, signal, current_price: float) -> bool:
        """Process a single signal through AI + Risk + Execution."""
        symbol = signal.symbol or self.symbol

        # AI veto gate
        self._update_status("AI", "ANALYZING", f"AI check: {symbol} {signal.direction}...")
        try:
            ind = self.indicators.get_all_indicators(
                self.processor.format_native_candles(
                    self.exchange.get_candles(symbol, interval="15m", limit=50)
                )
            )
        except Exception:
            ind = {}

        ai_result = self.ai.confirm_signal(
            direction=signal.direction,
            entry=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confluence_factors=signal.confluence_factors,
            indicators=ind,
            market_context=f"{signal.regime} | Strategy: {signal.strategy}",
        )

        if not ai_result.get("approved", True):
            reason = ai_result.get("reason", "AI vetoed")
            logger.info(f"AI VETO {symbol}: {reason}")
            self.db.log_ai_signal(symbol, f"VETO_{signal.direction}", reason, str(ai_result), {})
            return False

        # Risk validation
        open_positions = self.db.get_open_positions()
        approved, risk_reason = self.risk_manager.validate_trade(
            signal.entry_price, signal.stop_loss,
            signal.take_profit, signal.direction,
            open_position_count=len(open_positions)
        )

        if not approved:
            logger.warning(f"RISK REJECT {symbol}: {risk_reason}")
            return False

        # Position sizing
        quantity = self.risk_manager.calculate_position_size(
            signal.entry_price, signal.stop_loss
        )
        if quantity <= 0:
            return False

        # Execute
        if self.paper_trading:
            logger.info(f"PAPER TRADE: {signal.direction} {quantity:.6f} {symbol} [{signal.strategy}]")
            res = {"status": "success", "order_id": f"PAPER_{int(time.time())}"}
        else:
            res = self.exchange.place_order(
                symbol, signal.direction.lower(), "market",
                signal.entry_price, quantity
            )

        order_id = res.get("order_id", res.get("data", {}).get("order_id"))

        if res.get("status") == "success" or order_id:
            self.db.log_position(
                symbol=symbol, direction=signal.direction,
                entry_price=signal.entry_price, stop_loss=signal.stop_loss,
                take_profit=signal.take_profit, quantity=quantity,
                confluence_factors=signal.confluence_factors, order_id=order_id,
            )
            self.db.log_trade(
                symbol=symbol, side=signal.direction,
                price=signal.entry_price, quantity=quantity,
                status="FILLED", order_id=order_id,
                ai_reasoning=f"[{signal.strategy}|{signal.regime}] {signal.confluence_factors}",
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            )
            self.db.log_ai_signal(
                symbol, signal.direction,
                str(signal.confluence_factors), str(ai_result), {}
            )
            self.notifier.send_trade_executed(
                symbol, signal.direction, signal.entry_price,
                signal.stop_loss, signal.take_profit, quantity
            )
            logger.info(
                f"EXECUTED {symbol} {signal.direction} [{signal.strategy}|{signal.regime}] "
                f"Entry={signal.entry_price:.2f} SL={signal.stop_loss:.2f} "
                f"TP={signal.take_profit:.2f} Qty={quantity:.6f}"
            )
            return True

        logger.warning(f"ORDER FAILED {symbol}: {res}")
        return False

    def _sync_portfolio(self):
        try:
            portfolio_res = self.exchange.get_portfolio()
            if portfolio_res and "data" in portfolio_res:
                data = portfolio_res.get("data", {})
                if isinstance(data, dict) and "coinswitchx" in data:
                    balances = data["coinswitchx"]
                elif isinstance(data, list):
                    balances = data
                else:
                    balances = []

                for bal in balances:
                    if bal.get("currency") == "INR":
                        new_cap = float(bal.get("main_balance", self.risk_manager.capital))
                        self.risk_manager.capital = new_cap
                        stats = self.db.get_win_rate()
                        self.db.log_portfolio_snapshot(
                            capital=new_cap,
                            total_pnl=stats.get("total_pnl", 0.0),
                            win_count=stats.get("wins", 0),
                            loss_count=stats.get("losses", 0),
                            max_drawdown=self.risk_manager.max_drawdown * 100
                        )
                        break
        except Exception as e:
            logger.debug(f"Portfolio sync failed: {e}")

    def _monitor_all_positions(self):
        """
        Monitor ALL open positions for SL/TP/trailing stop.
        This runs REGARDLESS of session or news pauses.
        """
        open_positions = self.db.get_open_positions()

        for pos in open_positions:
            try:
                symbol = pos.get("symbol", self.symbol)
                ticker_res = self.exchange.get_ticker(symbol)
                current_price = float(ticker_res.get("data", {}).get("lastPrice", 0))

                if current_price <= 0:
                    continue

                # Trailing stop (two-phase: breakeven → ATR trail)
                try:
                    raw_candles = self.exchange.get_candles(symbol, interval="15m", limit=20)
                    df = self.processor.format_native_candles(raw_candles)
                    if not df.empty:
                        atr_series = self.indicators.calculate_atr(df["high"], df["low"], df["close"])
                        current_atr = atr_series.iloc[-1] if not pd.isna(atr_series.iloc[-1]) else 0
                    else:
                        current_atr = 0
                except Exception:
                    current_atr = 0

                if current_atr > 0:
                    new_sl = self.risk_manager.calculate_trailing_stop(pos, current_price, current_atr)
                    if new_sl is not None:
                        entry = pos.get("entry_price", 0)
                        old_sl = pos.get("stop_loss", 0)
                        self.db.update_position_sl(pos["id"], new_sl)
                        pos["stop_loss"] = new_sl

                        # Determine phase for logging
                        if abs(new_sl - entry) < 0.01:
                            logger.info(f"BREAKEVEN: {symbol} SL moved to entry {new_sl:.2f} (1R reached)")
                        else:
                            logger.info(f"ATR TRAIL: {symbol} SL {old_sl:.2f} → {new_sl:.2f}")

                # SL/TP
                hit = self.exchange.check_sl_tp_hit(pos, current_price)

                if hit == "SL":
                    pnl = self._calculate_pnl(pos, pos["stop_loss"])
                    self.db.close_position(pos["id"], pos["stop_loss"], pnl, "CLOSED_SL")
                    self.risk_manager.update_capital(pnl)
                    self.risk_manager.trigger_cooldown()
                    self.notifier.send_sl_triggered(
                        symbol, pos["direction"], pos["entry_price"],
                        pos["stop_loss"], abs(pnl)
                    )
                    logger.info(f"SL HIT: {symbol} | PnL: {pnl:.2f}")
                    self._snapshot_portfolio()

                elif hit == "TP":
                    pnl = self._calculate_pnl(pos, pos["take_profit"])
                    self.db.close_position(pos["id"], pos["take_profit"], pnl, "CLOSED_TP")
                    self.risk_manager.update_capital(pnl)
                    self.notifier.send_tp_triggered(
                        symbol, pos["direction"], pos["entry_price"],
                        pos["take_profit"], pnl
                    )
                    logger.info(f"TP HIT: {symbol} | PnL: +{pnl:.2f}")
                    self._snapshot_portfolio()

            except Exception as e:
                logger.error(f"Monitor error for {pos.get('symbol')}: {e}")

    def _snapshot_portfolio(self):
        stats = self.db.get_win_rate()
        self.db.log_portfolio_snapshot(
            self.risk_manager.capital, stats["total_pnl"],
            stats["wins"], stats["losses"],
            self.risk_manager.max_drawdown * 100
        )

    @staticmethod
    def _calculate_pnl(position: dict, exit_price: float) -> float:
        entry = position["entry_price"]
        qty = position["quantity"]
        direction = position["direction"]
        if direction == "BUY":
            return (exit_price - entry) * qty
        else:
            return (entry - exit_price) * qty

    def start(self):
        logger.info("QuatSystem v5.0 — Multi-Strategy Engine")
        mode = "PAPER" if self.paper_trading else "LIVE"
        scan = f"MULTI-PAIR ({self.max_signals_per_cycle} max)" if self.multi_pair_scan else "SINGLE"
        session_info = self.session_filter.get_session_info()
        logger.info(f"Mode: {mode} | Scan: {scan} | Session: {session_info['current_session']}")

        # Sync portfolio at startup so dashboard shows real balance
        self._sync_portfolio()

        while True:
            last_status = self.run_iteration()
            self._update_status(
                last_status.get("step", "IDLE"),
                last_status.get("action", "IDLE"),
                last_status.get("details", ""),
                is_sleeping=True
            )
            time.sleep(self.trading_interval * 60)


if __name__ == "__main__":
    bot = QuatBot()
    bot.start()
