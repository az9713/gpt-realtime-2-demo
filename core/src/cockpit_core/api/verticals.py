"""Vertical-pack-level read endpoints.

Today the only consumer is the Twilio webhook (which asks "is this
vertical's office open right now? if not, what greeting do I play?"),
but this is the natural place for any future per-vertical metadata
endpoints (tools list, modes list, etc.) that the cockpit or edge
needs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cockpit_core.verticals.business_hours import is_open_now
from cockpit_core.verticals.loader import PackLoadError, load_vertical

router = APIRouter(prefix="/v1/verticals", tags=["verticals"])


@router.get("/{name}/business-status")
async def business_status(name: str) -> dict[str, Any]:
    """Returns whether the vertical is currently open and (if not) the
    voicemail greeting to play. The Twilio webhook calls this on every
    inbound call to decide which TwiML to serve.
    """
    try:
        pack = load_vertical(name)
    except PackLoadError as e:
        raise HTTPException(404, str(e)) from e
    open_ = is_open_now(pack.business_hours)
    return {
        "vertical": pack.name,
        "open": open_,
        "voicemail_greeting": pack.voicemail_greeting,
        "supports_voicemail": "voicemail" in pack.modes,
        "business_hours": pack.business_hours,
    }
