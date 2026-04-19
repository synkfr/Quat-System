import os
import time
from typing import Tuple, Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()


class RiskManager:
    """
    Strict risk management gate. Every trade MUST pass through this module.
    v4.0: Added daily loss limit, max concurrent positions, cooldown after SL,
    ATR-based trailing stop.
    """

    def __init__(self, capital: float = None, max_risk_pct: float = None,
                 min_rr: float = None):
        self.capital = capital if capital is not None else float(os.getenv("INITIAL_CAPITAL", 0.0))
        self.max_risk_pct = max_risk_pct or float(os.getenv("MAX_RISK_PER_TRADE", 2.0))
        self.min_rr = min_rr or float(os.getenv("MIN_RR_RATIO", 2.0))
        self.peak_capital = self.capital
        self.max_drawdown = 0.0

        # v4.0: New risk controls
        self.daily_loss_limit_pct = float(os.getenv("DAILY_LOSS_LIMIT_PCT", 5.0))
        self.max_concurrent_positions = int(os.getenv("MAX_CONCURRENT_POSITIONS", 3))
        self.cooldown_cycles = int(os.getenv("COOLDOWN_CYCLES_AFTER_SL", 2))
        self.trailing_stop_enabled = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
        self.trailing_activation_r = float(os.getenv("TRAILING_ACTIVATION_R", 1.25))
        self.trailing_atr_multiplier = float(os.getenv("TRAILING_ATR_MULTIPLIER", 1.75))

        # Runtime state
        self._daily_pnl = 0.0
        self._daily_reset_time = time.time()
        self._cooldown_remaining = 0
        self._daily_start_capital = self.capital

    # ── SL / TP Calculation ─────────────────────────────────

    @staticmethod
    def calculate_stop_loss(entry: float, atr: float, direction: str) -> float:
        """SL = entry -/+ 1.5 * ATR. Always placed."""
        distance = 1.5 * atr
        if direction == "BUY":
            return entry - distance
        else:
            return entry + distance

    @staticmethod
    def calculate_take_profit(entry: float, stop_loss: float,
                              rr_ratio: float = 2.0) -> float:
        """TP = entry +/- (|entry - SL| * rr_ratio). Minimum 1:2."""
        risk_distance = abs(entry - stop_loss)
        reward_distance = risk_distance * rr_ratio
        if entry > stop_loss:  # BUY
            return entry + reward_distance
        else:  # SELL
            return entry - reward_distance

    # ── Position Sizing ─────────────────────────────────────

    def calculate_position_size(self, entry: float, stop_loss: float) -> float:
        """
        Position size = (capital * risk_pct) / |entry - SL|.
        Risk is capped at max_risk_pct of current capital.
        """
        risk_amount = self.capital * (self.max_risk_pct / 100.0)
        risk_per_unit = abs(entry - stop_loss)

        if risk_per_unit <= 0:
            return 0.0

        quantity = risk_amount / risk_per_unit
        return max(quantity, 0.0)

    # ── Risk / Reward Ratio ─────────────────────────────────

    @staticmethod
    def calculate_rr_ratio(entry: float, stop_loss: float,
                           take_profit: float) -> float:
        """Calculate the actual R:R ratio of a proposed trade."""
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        if risk <= 0:
            return 0.0
        return reward / risk

    # ── Trade Validation Gate ───────────────────────────────

    def validate_trade(self, entry: float, stop_loss: float,
                       take_profit: float, direction: str,
                       open_position_count: int = 0) -> Tuple[bool, str]:
        """
        Pre-execution validation. ALL checks must pass.
        v4.0: Added daily loss limit, max positions, cooldown checks.
        Returns (approved, reason).
        """
        # Check 0: Cooldown after SL
        if self._cooldown_remaining > 0:
            return False, f"Cooldown active: {self._cooldown_remaining} cycles remaining after SL"

        # Check 0b: Daily loss limit
        daily_limit_hit, daily_reason = self.check_daily_limit()
        if daily_limit_hit:
            return False, daily_reason

        # Check 0c: Max concurrent positions
        if open_position_count >= self.max_concurrent_positions:
            return False, f"Max {self.max_concurrent_positions} concurrent positions reached ({open_position_count} open)"

        # Check 1: Stop loss must exist and be on the correct side
        if direction == "BUY" and stop_loss >= entry:
            return False, f"Invalid SL for BUY: SL ({stop_loss:.2f}) must be below entry ({entry:.2f})"
        if direction == "SELL" and stop_loss <= entry:
            return False, f"Invalid SL for SELL: SL ({stop_loss:.2f}) must be above entry ({entry:.2f})"

        # Check 2: Take profit must be on the correct side
        if direction == "BUY" and take_profit <= entry:
            return False, f"Invalid TP for BUY: TP ({take_profit:.2f}) must be above entry ({entry:.2f})"
        if direction == "SELL" and take_profit >= entry:
            return False, f"Invalid TP for SELL: TP ({take_profit:.2f}) must be below entry ({entry:.2f})"

        # Check 3: R:R ratio must meet minimum
        rr = self.calculate_rr_ratio(entry, stop_loss, take_profit)
        if rr < self.min_rr:
            return False, f"R:R ratio {rr:.2f} below minimum {self.min_rr:.2f}"

        # Check 4: Position size must not exceed risk limit
        risk_amount = self.capital * (self.max_risk_pct / 100.0)
        position_size = self.calculate_position_size(entry, stop_loss)
        actual_risk = position_size * abs(entry - stop_loss)
        if actual_risk > risk_amount * 1.01:  # 1% tolerance for float math
            return False, f"Risk {actual_risk:.2f} exceeds max allowed {risk_amount:.2f}"

        # Check 5: Capital must be positive
        if self.capital <= 0:
            return False, "Insufficient capital"

        return True, "Trade approved"

    # ── Daily Loss Limit ────────────────────────────────────

    def check_daily_limit(self) -> Tuple[bool, str]:
        """Check if daily loss limit has been breached. Returns (breached, reason)."""
        # Reset daily PnL at midnight (or after 24h)
        if time.time() - self._daily_reset_time > 86400:
            self._daily_pnl = 0.0
            self._daily_reset_time = time.time()
            self._daily_start_capital = self.capital

        if self._daily_start_capital <= 0:
            return False, ""

        daily_loss_pct = abs(min(self._daily_pnl, 0)) / self._daily_start_capital * 100
        if daily_loss_pct >= self.daily_loss_limit_pct:
            return True, f"Daily loss limit hit: -{daily_loss_pct:.1f}% (limit: {self.daily_loss_limit_pct}%)"
        return False, ""

    # ── Cooldown Management ─────────────────────────────────

    def trigger_cooldown(self):
        """Called after a stop-loss hit to activate cooldown."""
        self._cooldown_remaining = self.cooldown_cycles

    def tick_cooldown(self):
        """Called each iteration to decrement cooldown."""
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

    # ── Trailing Stop ───────────────────────────────────────

    def calculate_trailing_stop(self, position: Dict, current_price: float,
                                 current_atr: float) -> Optional[float]:
        """
        ATR-based trailing stop.
        Activates after ~1.25R profit, trails at 1.75 ATR from price.
        Returns new SL if it should be moved, None otherwise.
        """
        if not self.trailing_stop_enabled:
            return None

        entry = position.get("entry_price", 0)
        current_sl = position.get("stop_loss", 0)
        direction = position.get("direction", "BUY")
        risk = abs(entry - current_sl)

        if risk <= 0 or current_atr <= 0:
            return None

        # Calculate current profit in R
        if direction == "BUY":
            profit = current_price - entry
            profit_r = profit / risk

            # Activate trailing after 1.25R profit
            if profit_r >= self.trailing_activation_r:
                new_sl = current_price - (self.trailing_atr_multiplier * current_atr)
                # Only move SL up, never down
                if new_sl > current_sl:
                    return new_sl
        else:  # SELL
            profit = entry - current_price
            profit_r = profit / risk

            if profit_r >= self.trailing_activation_r:
                new_sl = current_price + (self.trailing_atr_multiplier * current_atr)
                # Only move SL down, never up
                if new_sl < current_sl:
                    return new_sl

        return None

    # ── Capital Tracking ────────────────────────────────────

    def update_capital(self, pnl: float):
        """Update running capital and drawdown tracking after a trade closes."""
        self.capital += pnl
        self._daily_pnl += pnl

        if self.capital > self.peak_capital:
            self.peak_capital = self.capital

        if self.peak_capital > 0:
            current_drawdown = (self.peak_capital - self.capital) / self.peak_capital
            self.max_drawdown = max(self.max_drawdown, current_drawdown)

    def get_risk_summary(self) -> dict:
        """Current risk state for UI display."""
        daily_loss_pct = abs(min(self._daily_pnl, 0)) / self._daily_start_capital * 100 \
            if self._daily_start_capital > 0 else 0.0

        return {
            "capital": self.capital,
            "peak_capital": self.peak_capital,
            "max_drawdown_pct": self.max_drawdown * 100,
            "current_drawdown_pct": ((self.peak_capital - self.capital) / self.peak_capital * 100)
            if self.peak_capital > 0 else 0.0,
            "max_risk_per_trade": self.max_risk_pct,
            "max_risk_amount": self.capital * (self.max_risk_pct / 100.0),
            "min_rr_ratio": self.min_rr,
            "daily_pnl": self._daily_pnl,
            "daily_loss_pct": daily_loss_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "cooldown_remaining": self._cooldown_remaining,
            "max_concurrent_positions": self.max_concurrent_positions,
            "trailing_stop_enabled": self.trailing_stop_enabled,
        }
