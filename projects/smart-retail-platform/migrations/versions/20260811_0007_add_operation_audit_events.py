"""Add authenticated operation audit events.

Revision ID: 20260811_0007
Revises: 20260811_0006
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0007"
down_revision: str | None = "20260811_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_audit_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_role", sa.String(length=30), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=300), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_role IN ('operator', 'manager', 'pricing_lead', 'admin')",
            name="ck_operation_audit_events_role_valid",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_operation_audit_actor_occurred",
        "operation_audit_events",
        ["actor_id", "occurred_at"],
    )
    op.create_index(
        "ix_operation_audit_resource_occurred",
        "operation_audit_events",
        ["resource_type", "resource_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("operation_audit_events")
