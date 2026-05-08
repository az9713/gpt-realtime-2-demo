"""Store layer: typed dataclasses + asyncpg queries.

Single source of truth for durable conversation data. All public
functions accept either a `Connection`, `Pool`, or default to the
global pool.
"""

from cockpit_core.store.approvals import (
    Approval,
    create_approval,
    get_approval,
    list_pending_approvals,
    resolve_approval,
)
from cockpit_core.store.conversations import (
    Conversation,
    create_conversation,
    end_conversation,
    get_conversation,
    list_recent_conversations,
)
from cockpit_core.store.tool_calls import (
    ToolCall,
    create_tool_call,
    get_tool_call,
    list_tool_calls,
    update_tool_call_status,
)
from cockpit_core.store.trace_events import TraceEvent, insert_trace_events, list_trace_events
from cockpit_core.store.turns import Turn, append_turn, list_turns

__all__ = [
    "Approval",
    "Conversation",
    "ToolCall",
    "TraceEvent",
    "Turn",
    "append_turn",
    "create_approval",
    "create_conversation",
    "create_tool_call",
    "end_conversation",
    "get_approval",
    "get_conversation",
    "get_tool_call",
    "insert_trace_events",
    "list_pending_approvals",
    "list_recent_conversations",
    "list_tool_calls",
    "list_trace_events",
    "list_turns",
    "resolve_approval",
    "update_tool_call_status",
]
