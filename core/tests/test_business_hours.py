"""Phase 4 — business_hours predicate."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cockpit_core.verticals.business_hours import is_open_now, parse_hhmm


def test_parse_hhmm():
    assert parse_hhmm("09:00").hour == 9
    assert parse_hhmm("17:30").minute == 30


def test_open_during_business_hours_weekday():
    bh = {"tz": "America/Chicago", "open": "09:00", "close": "17:00", "days": [1, 2, 3, 4, 5]}
    # Tuesday at 10am Chicago time → open
    now = datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert is_open_now(bh, now=now) is True


def test_closed_after_hours():
    bh = {"tz": "America/Chicago", "open": "09:00", "close": "17:00", "days": [1, 2, 3, 4, 5]}
    now = datetime(2026, 5, 12, 22, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert is_open_now(bh, now=now) is False


def test_closed_on_weekend():
    bh = {"tz": "America/Chicago", "open": "09:00", "close": "17:00", "days": [1, 2, 3, 4, 5]}
    sat = datetime(2026, 5, 16, 11, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert is_open_now(bh, now=sat) is False
    sun = datetime(2026, 5, 17, 11, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert is_open_now(bh, now=sun) is False


def test_no_business_hours_means_always_open():
    assert is_open_now(None) is True
    assert is_open_now({}) is True


def test_window_wrapping_midnight():
    # An overnight on-call window: 22:00 - 06:00
    bh = {"tz": "UTC", "open": "22:00", "close": "06:00", "days": [1, 2, 3, 4, 5, 6, 7]}
    inside_late = datetime(2026, 5, 12, 23, 30, tzinfo=ZoneInfo("UTC"))
    inside_early = datetime(2026, 5, 12, 5, 30, tzinfo=ZoneInfo("UTC"))
    outside = datetime(2026, 5, 12, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert is_open_now(bh, now=inside_late) is True
    assert is_open_now(bh, now=inside_early) is True
    assert is_open_now(bh, now=outside) is False


def test_timezone_translation():
    """Caller's clock isn't UTC. Predicate must convert."""
    bh = {"tz": "America/Chicago", "open": "09:00", "close": "17:00", "days": [1, 2, 3, 4, 5]}
    # 14:00 UTC on a Tuesday = 09:00 Chicago — exactly open.
    utc_now = datetime(2026, 5, 12, 14, 0, tzinfo=ZoneInfo("UTC"))
    assert is_open_now(bh, now=utc_now) is True


def test_loader_surfaces_business_hours():
    """The HVAC pack ships business_hours; the loader must surface them."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "core" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    for k in list(sys.modules):
        if k == "verticals" or k.startswith("verticals."):
            del sys.modules[k]

    from cockpit_core.verticals.loader import load_vertical_from_path

    pack = load_vertical_from_path(repo_root / "verticals" / "hvac")
    assert pack.business_hours is not None
    assert pack.business_hours.get("tz") == "America/Chicago"
    assert pack.voicemail_greeting is not None
    greeting = pack.voicemail_greeting.lower()
    assert "after-hours" in greeting or "leave" in greeting
    assert "voicemail" in pack.modes
