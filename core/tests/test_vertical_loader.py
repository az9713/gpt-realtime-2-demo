"""Verifies the HVAC pack loads without error and exposes its tools."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HVAC_DIR = REPO_ROOT / "verticals" / "hvac"


def _ensure_path():
    src = REPO_ROOT / "core" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


@pytest.fixture(autouse=True)
def _isolate_modules():
    """Each loader test starts with a clean `verticals` namespace."""
    for k in list(sys.modules):
        if k == "verticals" or k.startswith("verticals."):
            del sys.modules[k]
    _ensure_path()
    yield


def test_hvac_pack_loads():
    from cockpit_core.verticals.loader import load_vertical_from_path

    pack = load_vertical_from_path(HVAC_DIR)
    assert pack.name == "hvac"
    names = {t.name for t in pack.tools}
    assert {"parts_lookup", "warranty_check", "schedule_move", "dispatch_truck"} <= names


def test_hvac_dangerous_tools_have_phrases():
    from cockpit_core.verticals.loader import load_vertical_from_path

    pack = load_vertical_from_path(HVAC_DIR)
    move = pack.registry.get("schedule_move")
    dispatch = pack.registry.get("dispatch_truck")
    assert move.preamble == "Reggie, do it"
    assert dispatch.preamble == "Reggie, send the truck"


def test_invalid_pack_dir_raises():
    from cockpit_core.verticals.loader import PackLoadError, load_vertical_from_path

    with pytest.raises(PackLoadError):
        load_vertical_from_path(HVAC_DIR.parent / "does-not-exist")


def test_hvac_read_tools_have_no_approval():
    from cockpit_core.verticals.loader import load_vertical_from_path

    pack = load_vertical_from_path(HVAC_DIR)
    parts = pack.registry.get("parts_lookup")
    assert parts.blast_radius == "read"
