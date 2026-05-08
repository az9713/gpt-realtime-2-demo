"""Observability spine: structured tracer + sinks + notifier."""

from cockpit_core.observability.tracer import (
    Tracer,
    emit,
    get_tracer,
    shutdown_tracer,
    start_tracer,
    tracer_stats,
)

__all__ = [
    "Tracer",
    "emit",
    "get_tracer",
    "shutdown_tracer",
    "start_tracer",
    "tracer_stats",
]
