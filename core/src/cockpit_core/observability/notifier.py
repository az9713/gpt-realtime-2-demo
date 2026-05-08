"""Redis pub/sub notifier for approval state changes (Phase 4 Task 19)."""

from __future__ import annotations

import json
from typing import Any

from cockpit_core.logging import get_logger
from cockpit_core.redis_client import get_redis

logger = get_logger("notifier")

APPROVAL_CHANNEL = "approvals"
SESSION_CHANNEL_PREFIX = "session"


def _session_channel(conversation_id: str) -> str:
    return f"{SESSION_CHANNEL_PREFIX}:{conversation_id}"


async def publish_approval(*, kind: str, conversation_id: str, payload: dict[str, Any]) -> None:
    """Publish an approval event to the approvals channel + the per-session channel."""
    msg = json.dumps(
        {"kind": kind, "conversation_id": conversation_id, "payload": payload},
        default=str,
    )
    redis = get_redis()
    try:
        await redis.publish(APPROVAL_CHANNEL, msg)
        await redis.publish(_session_channel(conversation_id), msg)
    except Exception as e:
        logger.error("approval_publish_failed", err=str(e), kind=kind)


async def publish_session_event(
    *,
    conversation_id: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
    msg = json.dumps(
        {"kind": kind, "conversation_id": conversation_id, "payload": payload},
        default=str,
    )
    try:
        await get_redis().publish(_session_channel(conversation_id), msg)
    except Exception as e:
        logger.error("session_publish_failed", err=str(e), kind=kind)
