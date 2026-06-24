"""widen conversations.mode CHECK to allow voicemail and notetaker

Revision ID: 0002_widen_modes
Revises: 0001_initial
Create Date: 2026-05-08

Forward-only. The original 0001_initial constraint allowed only
('realtime2', 'translate'). The five whisper-enabled features need two
new mode values: 'voicemail' (after-hours overflow handler) and
'notetaker' (dispatcher silently transcribed). 'translate' stays valid;
nothing is removed.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_widen_modes"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "conversations_mode_check",
        "conversations",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "conversations_mode_check",
        "conversations",
        "mode IN ('realtime2', 'translate', 'voicemail', 'notetaker')",
        schema="app",
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only migrations")
