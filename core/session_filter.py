import os
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional
from dotenv import load_dotenv

load_dotenv()


class SessionFilter:
    """
    Trading session time filter.
    Controls when new trades can be opened based on global market sessions.

    Sessions (UTC):
      London:   08:00 - 16:30 UTC  (high volatility, breakouts)
      New York: 13:30 - 21:00 UTC  (trends, momentum)
      Asian:    00:00 - 08:00 UTC  (low vol, chop — NO new trades)

    Rules:
      - New trade entries ONLY during London or New York sessions.
      - Asian session: NO new trades (avoid chop/fakeouts).
      - Existing trades can be CLOSED at any time (SL/TP monitoring never stops).
      - London/NY overlap (13:30-16:30 UTC) is the highest-liquidity window.
    """

    def __init__(self):
        self.enabled = os.getenv("SESSION_FILTER_ENABLED", "true").lower() == "true"

        # Session times in UTC (hour, minute)
        self.london_start = (8, 0)
        self.london_end = (16, 30)
        self.ny_start = (13, 30)
        self.ny_end = (21, 0)
        self.asian_start = (0, 0)
        self.asian_end = (8, 0)

    def can_open_new_trade(self) -> Tuple[bool, str]:
        """
        Check if current time allows new trade entries.
        Returns (allowed, session_name).
        Existing position management (SL/TP/trailing) is ALWAYS allowed.
        """
        if not self.enabled:
            return True, "FILTER_DISABLED"

        now = datetime.now(timezone.utc)
        hour, minute = now.hour, now.minute
        current_minutes = hour * 60 + minute

        london_start_m = self.london_start[0] * 60 + self.london_start[1]
        london_end_m = self.london_end[0] * 60 + self.london_end[1]
        ny_start_m = self.ny_start[0] * 60 + self.ny_start[1]
        ny_end_m = self.ny_end[0] * 60 + self.ny_end[1]

        # London/NY overlap (highest liquidity)
        if ny_start_m <= current_minutes <= london_end_m:
            return True, "LONDON_NY_OVERLAP"

        # London session
        if london_start_m <= current_minutes <= london_end_m:
            return True, "LONDON"

        # New York session
        if ny_start_m <= current_minutes <= ny_end_m:
            return True, "NEW_YORK"

        # Asian session or off-hours — no new trades
        return False, "ASIAN_SESSION"

    def get_session_info(self) -> dict:
        """Current session status for UI display."""
        can_trade, session = self.can_open_new_trade()
        now = datetime.now(timezone.utc)

        # Calculate time until next trading window
        hour, minute = now.hour, now.minute
        current_minutes = hour * 60 + minute
        london_start_m = self.london_start[0] * 60 + self.london_start[1]

        if not can_trade:
            # Minutes until London opens
            if current_minutes < london_start_m:
                mins_until = london_start_m - current_minutes
            else:
                mins_until = (24 * 60 - current_minutes) + london_start_m
            next_open = f"{mins_until // 60}h {mins_until % 60}m"
        else:
            next_open = "NOW"

        return {
            "enabled": self.enabled,
            "can_trade": can_trade,
            "current_session": session,
            "utc_time": now.strftime("%H:%M UTC"),
            "next_trading_window": next_open,
            "note": "Position management (SL/TP) always active" if not can_trade else "",
        }
