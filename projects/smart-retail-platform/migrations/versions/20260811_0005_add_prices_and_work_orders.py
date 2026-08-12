"""Add price and work-order operations for Copilot tools.

Revision ID: 20260811_0005
Revises: 20260811_0004
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0005"
down_revision: str | None = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("store_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_prices_amount_positive"),
        sa.ForeignKeyConstraint(["sku"], ["skus.sku"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.store_id"]),
        sa.PrimaryKeyConstraint("store_id", "sku"),
    )
    op.create_table(
        "price_changes",
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("new_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "new_price > 0", name="ck_price_changes_new_price_positive"
        ),
        sa.ForeignKeyConstraint(["sku"], ["skus.sku"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.store_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_price_changes_sku", "price_changes", ["sku"])
    op.create_index("ix_price_changes_store_id", "price_changes", ["store_id"])

    op.create_table(
        "work_orders",
        sa.Column("ticket_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_work_orders_priority_valid",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved')",
            name="ck_work_orders_status_valid",
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.store_id"]),
        sa.PrimaryKeyConstraint("ticket_id"),
    )
    op.create_index("ix_work_orders_store_id", "work_orders", ["store_id"])


def downgrade() -> None:
    op.drop_table("work_orders")
    op.drop_table("price_changes")
    op.drop_table("prices")
