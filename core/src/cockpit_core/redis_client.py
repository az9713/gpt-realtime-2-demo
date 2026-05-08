"""Async redis client wrapper used for pub/sub + ephemeral state."""

from __future__ import annotations

from redis.asyncio import Redis

from cockpit_core.settings import Settings, get_settings

_client: Redis | None = None


def get_redis(settings: Settings | None = None) -> Redis:
    global _client
    if _client is not None:
        return _client
    s = settings or get_settings()
    _client = Redis(host=s.redis_host, port=s.redis_port, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
