"""Add persistent human approval workflow.

Revision ID: 20260811_0006
Revises: 20260811_0005
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0006"
down_revision: str | None = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("requester", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_role", sa.String(length=30), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executing', 'executed', 'failed')",
            name="ck_approval_requests_status_valid",
        ),
        sa.CheckConstraint(
            "decided_role IS NULL OR decided_role IN "
            "('operator', 'manager', 'pricing_lead', 'admin')",
            name="ck_approval_requests_role_valid",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_approval_requests_status", "approval_requests", ["status"]
    )
    op.create_index(
        "ix_approval_requests_tool_name", "approval_requests", ["tool_name"]
    )


def downgrade() -> None:
    op.drop_table("approval_requests")
