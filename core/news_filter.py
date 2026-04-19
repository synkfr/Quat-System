import os
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Known FOMC/CPI dates for 2026 (fallback when API is unavailable)
# Format: (month, day, description)
KNOWN_EVENTS_2026 = [
    (1, 14, "CPI Data Release"),
    (1, 29, "FOMC Meeting"),
    (2, 12, "CPI Data Release"),
    (3, 12, "CPI Data Release"),
    (3, 19, "FOMC Meeting"),
    (4, 10, "CPI Data Release"),
    (5, 7, "FOMC Meeting"),
    (5, 13, "CPI Data Release"),
    (6, 11, "CPI Data Release"),
    (6, 18, "FOMC Meeting"),
    (7, 15, "CPI Data Release"),
    (7, 30, "FOMC Meeting"),
    (8, 12, "CPI Data Release"),
    (9, 10, "CPI Data Release"),
    (9, 17, "FOMC Meeting"),
    (10, 14, "CPI Data Release"),
    (11, 5, "FOMC Meeting"),
    (11, 12, "CPI Data Release"),
    (12, 10, "CPI Data Release"),
    (12, 17, "FOMC Meeting"),
]


class NewsFilter:
    """
    Automated kill-switch that pauses trading during high-impact
    macroeconomic events (CPI, FOMC, crypto regulation news).
    v4.0: Added CryptoCompare news API, weekend filter, weighted keywords.
    """

    # Weighted keywords: higher weight = more likely to trigger kill-switch
    KILL_KEYWORDS = {
        # Instant kill (weight 3)
        "FOMC": 3, "CPI": 3, "Federal Reserve": 3, "Fed Rate": 3,
        "Interest Rate Decision": 3, "crypto ban": 3,
        # High impact (weight 2)
        "Non-Farm Payrolls": 2, "NFP": 2, "SEC crypto": 2,
        "crypto regulation": 2, "Bitcoin ETF": 2, "stablecoin regulation": 2,
        # Moderate (weight 1)
        "employment data": 1, "GDP release": 1, "inflation data": 1,
        "monetary policy": 1, "quantitative tightening": 1,
    }

    KILL_THRESHOLD = 2  # Minimum keyword weight to trigger pause

    def __init__(self):
        self.blackout_before = timedelta(
            minutes=int(os.getenv("NEWS_BLACKOUT_BEFORE_MIN", 30))
        )
        self.blackout_after = timedelta(
            minutes=int(os.getenv("NEWS_BLACKOUT_AFTER_MIN", 60))
        )
        self.weekend_pause = os.getenv("WEEKEND_PAUSE", "false").lower() == "true"
        self._event_cache: List[Dict[str, Any]] = []
        self._news_cache: List[Dict[str, Any]] = []
        self._last_fetch: Optional[float] = None
        self._last_news_fetch: Optional[float] = None
        self._cache_ttl = 3600  # Refresh every hour
        self._news_cache_ttl = 900  # News refresh every 15min
        self._manual_pause = False
        self._manual_pause_reason = ""

    # ── Public API ──────────────────────────────────────────

    def is_trading_safe(self) -> Tuple[bool, Optional[str]]:
        """
        Returns (safe, reason).
        False if within blackout window of any high-impact event,
        if manual pause is active, or if weekend pause is enabled on weekends.
        """
        if self._manual_pause:
            return False, f"Manual pause: {self._manual_pause_reason}"

        # Weekend check
        if self.weekend_pause:
            now = datetime.now(timezone.utc)
            if now.weekday() >= 5:  # Saturday=5, Sunday=6
                return False, "Weekend pause active (reduced volume/liquidity)"

        # Calendar events
        events = self._get_events()
        now = datetime.now(timezone.utc)

        for event in events:
            event_time = event["time"]
            window_start = event_time - self.blackout_before
            window_end = event_time + self.blackout_after

            if window_start <= now <= window_end:
                remaining = window_end - now
                return False, (
                    f"BLACKOUT: {event['description']} "
                    f"(resumes in {int(remaining.total_seconds() // 60)}min)"
                )

        # Real-time crypto news check
        news_safe, news_reason = self._check_crypto_news()
        if not news_safe:
            return False, news_reason

        return True, None

    def get_upcoming_events(self, hours_ahead: int = 48) -> List[Dict[str, Any]]:
        """Return events within the next N hours for UI display."""
        events = self._get_events()
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)

        upcoming = []
        for event in events:
            if now <= event["time"] <= cutoff:
                delta = event["time"] - now
                hours = int(delta.total_seconds() // 3600)
                minutes = int((delta.total_seconds() % 3600) // 60)
                upcoming.append({
                    "time": event["time"].isoformat(),
                    "description": event["description"],
                    "impact": event.get("impact", "HIGH"),
                    "countdown": f"{hours}h {minutes}m",
                })
        return upcoming

    def get_next_event(self) -> Optional[Dict[str, Any]]:
        """Return the single next upcoming event."""
        upcoming = self.get_upcoming_events(hours_ahead=168)  # 1 week
        return upcoming[0] if upcoming else None

    def set_manual_pause(self, paused: bool, reason: str = ""):
        """Allow manual override from UI."""
        self._manual_pause = paused
        self._manual_pause_reason = reason

    def get_status(self) -> Dict[str, Any]:
        """Full status for UI display."""
        safe, reason = self.is_trading_safe()
        return {
            "is_safe": safe,
            "reason": reason,
            "manual_pause": self._manual_pause,
            "weekend_pause": self.weekend_pause,
            "upcoming_events": self.get_upcoming_events(),
            "next_event": self.get_next_event(),
            "blackout_before_min": int(self.blackout_before.total_seconds() // 60),
            "blackout_after_min": int(self.blackout_after.total_seconds() // 60),
        }

    # ── Crypto News API ─────────────────────────────────────

    def _check_crypto_news(self) -> Tuple[bool, Optional[str]]:
        """Check CryptoCompare news for high-impact crypto headlines."""
        now = time.time()
        if self._last_news_fetch and (now - self._last_news_fetch) < self._news_cache_ttl:
            # Use cached result
            for item in self._news_cache:
                return False, f"CRYPTO NEWS: {item['title'][:80]}"
            return True, None

        try:
            resp = requests.get(
                "https://min-api.cryptocompare.com/data/v2/news/?lang=EN",
                timeout=10,
                headers={"User-Agent": "QuatSystem/4.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                articles = data.get("Data", [])[:20]

                kill_articles = []
                for article in articles:
                    title = article.get("title", "")
                    body = article.get("body", "")[:200]
                    text = (title + " " + body).lower()

                    max_weight = 0
                    for keyword, weight in self.KILL_KEYWORDS.items():
                        if keyword.lower() in text:
                            max_weight = max(max_weight, weight)

                    # Only trigger on published_on within last 2 hours
                    published = article.get("published_on", 0)
                    age_hours = (time.time() - published) / 3600

                    if max_weight >= self.KILL_THRESHOLD and age_hours < 2:
                        kill_articles.append({
                            "title": title,
                            "weight": max_weight,
                            "age_hours": age_hours,
                        })

                self._news_cache = kill_articles
                self._last_news_fetch = now

                if kill_articles:
                    top = kill_articles[0]
                    return False, f"CRYPTO NEWS: {top['title'][:80]}"

        except Exception as e:
            logger.debug(f"CryptoCompare news fetch failed: {e}")

        return True, None

    # ── Event Fetching ──────────────────────────────────────

    def _get_events(self) -> List[Dict[str, Any]]:
        """Get events, using cache if fresh, otherwise refresh."""
        now = time.time()
        if self._last_fetch and (now - self._last_fetch) < self._cache_ttl:
            return self._event_cache

        events = []

        # Always merge in known hardcoded events
        events.extend(self._get_hardcoded_events())

        # Deduplicate by date + description
        seen = set()
        unique = []
        for evt in events:
            key = (evt["time"].date(), evt["description"])
            if key not in seen:
                seen.add(key)
                unique.append(evt)

        self._event_cache = sorted(unique, key=lambda x: x["time"])
        self._last_fetch = now
        return self._event_cache

    def _get_hardcoded_events(self) -> List[Dict[str, Any]]:
        """
        Fallback: known FOMC/CPI dates for the current year.
        Events are set at 18:30 UTC (typical release time).
        """
        events = []
        now = datetime.now(timezone.utc)
        year = now.year

        for month, day, description in KNOWN_EVENTS_2026:
            try:
                event_time = datetime(year, month, day, 18, 30, tzinfo=timezone.utc)
                # Only include events within +/- 7 days of now
                if abs((event_time - now).days) <= 7:
                    events.append({
                        "time": event_time,
                        "description": description,
                        "impact": "HIGH",
                        "source": "hardcoded",
                    })
            except ValueError:
                continue

        return events
