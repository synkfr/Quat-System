import os
import smtplib
import time
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class EmailNotifier:
    """
    SMTP-based email notification system for trade lifecycle events.
    Rate-limited to prevent spam. Graceful failure (logs errors, never crashes bot).
    """

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.sender = os.getenv("SMTP_USER", "")
        self.password = os.getenv("SMTP_PASS", "")
        self.recipient = os.getenv("ALERT_RECIPIENT", "")
        self.enabled = bool(self.sender and self.password and self.recipient)

        # Rate limiting: event_type -> last_sent_timestamp
        self._rate_limiter: dict = {}
        self._rate_limit_seconds = 300  # 5 minutes per event type

    # ── Public Alert Methods ────────────────────────────────

    def send_trade_executed(self, symbol: str, direction: str, entry: float,
                            stop_loss: float, take_profit: float,
                            quantity: float):
        """Notify on trade execution."""
        subject = f"TRADE EXECUTED: {direction} {symbol}"
        body = self._format_trade_body(
            title="Trade Executed",
            symbol=symbol, direction=direction, entry=entry,
            stop_loss=stop_loss, take_profit=take_profit, quantity=quantity,
        )
        self._send("trade_executed", subject, body)

    def send_sl_triggered(self, symbol: str, direction: str, entry: float,
                          stop_loss: float, loss_amount: float):
        """Notify when stop loss is hit."""
        subject = f"STOP LOSS HIT: {symbol}"
        body = f"""
STOP LOSS TRIGGERED
{'=' * 40}

Symbol:      {symbol}
Direction:   {direction}
Entry:       {entry:.2f}
Stop Loss:   {stop_loss:.2f}
Loss:        {loss_amount:.2f}
Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self._send("sl_triggered", subject, body)

    def send_tp_triggered(self, symbol: str, direction: str, entry: float,
                          take_profit: float, profit_amount: float):
        """Notify when take profit is hit."""
        subject = f"TAKE PROFIT HIT: {symbol}"
        body = f"""
TAKE PROFIT TRIGGERED
{'=' * 40}

Symbol:      {symbol}
Direction:   {direction}
Entry:       {entry:.2f}
Take Profit: {take_profit:.2f}
Profit:      +{profit_amount:.2f}
Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self._send("tp_triggered", subject, body)

    def send_system_pause(self, reason: str, resume_estimate: str = ""):
        """Notify when the system pauses due to news events."""
        subject = "SYSTEM PAUSED: News Kill-Switch Activated"
        body = f"""
TRADING PAUSED
{'=' * 40}

Reason:      {reason}
Resume Est:  {resume_estimate or 'TBD'}
Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

All trading activity has been automatically
suspended. The system will resume when the
blackout window expires.
"""
        self._send("system_pause", subject, body)

    def send_system_resume(self):
        """Notify when the system resumes after a pause."""
        subject = "SYSTEM RESUMED: Trading Active"
        body = f"""
TRADING RESUMED
{'=' * 40}

Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

The blackout window has expired.
Trading activity has been resumed.
"""
        self._send("system_resume", subject, body)

    # ── Internal ────────────────────────────────────────────

    def _format_trade_body(self, title: str, symbol: str, direction: str,
                            entry: float, stop_loss: float,
                            take_profit: float, quantity: float) -> str:
        risk = abs(entry - stop_loss) * quantity
        reward = abs(take_profit - entry) * quantity
        rr = reward / risk if risk > 0 else 0

        return f"""
{title.upper()}
{'=' * 40}

Symbol:      {symbol}
Direction:   {direction}
Entry:       {entry:.2f}
Stop Loss:   {stop_loss:.2f}
Take Profit: {take_profit:.2f}
Quantity:    {quantity:.6f}
Risk:        {risk:.2f}
Reward:      {reward:.2f}
R:R Ratio:   1:{rr:.1f}
Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _send(self, event_type: str, subject: str, body: str):
        """
        Core email sender with rate limiting and error handling.
        Never raises — logs errors and continues.
        """
        if not self.enabled:
            logger.debug(f"Email not configured, skipping: {subject}")
            return

        # Rate limit check
        now = time.time()
        last_sent = self._rate_limiter.get(event_type, 0)
        if now - last_sent < self._rate_limit_seconds:
            logger.debug(f"Rate limited, skipping email: {event_type}")
            return

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[PAPER] {subject}"
            msg["From"] = self.sender
            msg["To"] = self.recipient

            # Plain text body (matches terminal aesthetic)
            text_part = MIMEText(body, "plain", "utf-8")
            msg.attach(text_part)

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipient, msg.as_string())

            self._rate_limiter[event_type] = now
            logger.info(f"Email sent: {subject}")

        except Exception as e:
            logger.error(f"Email send failed: {e}")
