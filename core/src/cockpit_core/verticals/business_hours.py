"""Business-hours predicate used by Phase 4 (voicemail / overflow).

A vertical pack declares its hours in pack.yaml, e.g.::

    business_hours:
      tz: America/Chicago
      open: "09:00"
      close: "17:00"
      days: [1, 2, 3, 4, 5]   # Mon-Fri (ISO weekday: 1=Mon, 7=Sun)

When `is_open_now()` returns False, the Twilio webhook serves a
voicemail TwiML instead of the agent TwiML.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo


def parse_hhmm(s: str) -> time:
    """'09:00' -> time(9, 0)."""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid HH:MM string: {s!r}")
    h, m = int(parts[0]), int(parts[1])
    return time(hour=h, minute=m)


def is_open_now(business_hours: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """True when the current local time falls inside the configured window.

    A pack with no `business_hours` is treated as always-open (the
    default — voicemail flow opt-in only).
    """
    if not business_hours:
        return True
    tz_name = business_hours.get("tz", "UTC")
    open_s = str(business_hours.get("open", "00:00"))
    close_s = str(business_hours.get("close", "23:59"))
    days = list(business_hours.get("days", [1, 2, 3, 4, 5, 6, 7]))
    tz = ZoneInfo(str(tz_name))
    n = (now.astimezone(tz) if now else datetime.now(tz))
    if n.isoweekday() not in days:
        return False
    open_t = parse_hhmm(open_s)
    close_t = parse_hhmm(close_s)
    cur = n.time()
    if open_t <= close_t:
        return open_t <= cur < close_t
    # window wraps midnight (e.g. 22:00 - 06:00)
    return cur >= open_t or cur < close_t
