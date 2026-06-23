"""audit_divergences table for Phase 5

Revision ID: 0003_audit_divergences
Revises: 0002_widen_modes
Create Date: 2026-05-08

Adds a new table holding per-turn divergences detected by the audit
runner: places where the agent's transcript (model='realtime2' or
'translate') disagreed with the canonical whisper transcript.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_audit_divergences"
down_revision: str | Sequence[str] | None = "0002_widen_modes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_divergences",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("app.conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_turn_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "canonical_turn_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("agent_text", sa.Text(), nullable=True),
        sa.Column("canonical_text", sa.Text(), nullable=True),
        sa.Column(
            "flagged_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('paraphrase', 'omission', 'addition', 'mismatch')",
            name="audit_divergences_kind_check",
        ),
        schema="app",
    )
    op.create_index(
        "ix_audit_divergences_conversation_id",
        "audit_divergences",
        ["conversation_id"],
        schema="app",
    )
    op.create_index(
        "ix_audit_divergences_flagged_at",
        "audit_divergences",
        ["flagged_at"],
        schema="app",
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only migrations")
