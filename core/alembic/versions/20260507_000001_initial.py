"""initial schema: conversations, turns, tool_calls, approvals, trace_events

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    op.create_table(
        "conversations",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("customer_ref", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("agent_persona", sa.Text(), nullable=True),
        sa.Column("started_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.CheckConstraint(
            "surface IN ('browser', 'phone')", name="conversations_surface_check"
        ),
        sa.CheckConstraint(
            "mode IN ('realtime2', 'translate')", name="conversations_mode_check"
        ),
        schema="app",
    )
    op.create_index(
        "ix_conversations_started_at",
        "conversations",
        ["started_at"],
        schema="app",
    )
    op.create_index(
        "ix_conversations_vertical",
        "conversations",
        ["vertical"],
        schema="app",
    )

    op.create_table(
        "turns",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("audio_uri", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ts", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'agent', 'tool', 'system')",
            name="turns_role_check",
        ),
        schema="app",
    )
    op.create_index("ix_turns_conversation_id", "turns", ["conversation_id"], schema="app")
    op.create_index("ix_turns_ts", "turns", ["ts"], schema="app")

    op.create_table(
        "approvals",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tool_call_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "resolved_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_via", sa.Text(), nullable=True),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('approved', 'denied', 'timeout')",
            name="approvals_decision_check",
        ),
        sa.CheckConstraint(
            "decided_via IS NULL OR decided_via IN ('voice', 'cockpit', 'auto')",
            name="approvals_decided_via_check",
        ),
        schema="app",
    )
    op.create_index(
        "ix_approvals_conversation_id",
        "approvals",
        ["conversation_id"],
        schema="app",
    )
    op.create_index("ix_approvals_requested_at", "approvals", ["requested_at"], schema="app")

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("args_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("result_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("blast_radius", sa.Text(), nullable=False),
        sa.Column(
            "approval_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.approvals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'denied', 'executed', 'failed')",
            name="tool_calls_status_check",
        ),
        sa.CheckConstraint(
            "blast_radius IN ('read', 'safe-write', 'dangerous')",
            name="tool_calls_blast_radius_check",
        ),
        schema="app",
    )
    op.create_index(
        "ix_tool_calls_conversation_id",
        "tool_calls",
        ["conversation_id"],
        schema="app",
    )
    op.create_index("ix_tool_calls_started_at", "tool_calls", ["started_at"], schema="app")

    op.create_table(
        "trace_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_trace_events_conversation_id",
        "trace_events",
        ["conversation_id"],
        schema="app",
    )
    op.create_index("ix_trace_events_ts", "trace_events", ["ts"], schema="app")
    op.create_index("ix_trace_events_kind", "trace_events", ["kind"], schema="app")


def downgrade() -> None:
    raise NotImplementedError("forward-only migrations")
