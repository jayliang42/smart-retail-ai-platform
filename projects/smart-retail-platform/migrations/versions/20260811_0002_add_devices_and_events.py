"""Add device registration and event ingestion tables.

Revision ID: 20260811_0002
Revises: 20260811_0001
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=64), nullable=False),
        sa.Column("device_type", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "device_type IN ('refrigeration_unit', 'temperature_sensor', 'pos_terminal', "
            "'camera', 'edge_gateway', 'other')",
            name="ck_devices_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'maintenance')",
            name="ck_devices_status_valid",
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.store_id"]),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_index("ix_devices_store_id", "devices", ["store_id"])

    op.create_table(
        "device_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_device_events_device_id", "device_events", ["device_id"])
    op.create_index(
        "ix_device_events_device_observed_at",
        "device_events",
        ["device_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("device_events")
    op.drop_table("devices")
