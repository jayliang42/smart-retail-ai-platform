"""Create the initial retail operations schema.

Revision ID: 20260811_0001
Revises: None
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        name
        for constraint in inspector.get_check_constraints(table_name)
        if (name := constraint.get("name")) is not None
    }


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        name
        for index in inspector.get_indexes(table_name)
        if (name := index.get("name")) is not None
    }


def upgrade() -> None:
    """Create a fresh schema or baseline the pre-migration v0.1 development schema."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "stores" not in tables:
        op.create_table(
            "stores",
            sa.Column("store_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.PrimaryKeyConstraint("store_id"),
        )

    if "skus" not in tables:
        op.create_table(
            "skus",
            sa.Column("sku", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.PrimaryKeyConstraint("sku"),
        )

    if "inventory" not in tables:
        op.create_table(
            "inventory",
            sa.Column("store_id", sa.String(length=64), nullable=False),
            sa.Column("sku", sa.String(length=64), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "quantity >= 0", name="ck_inventory_quantity_non_negative"
            ),
            sa.ForeignKeyConstraint(["sku"], ["skus.sku"]),
            sa.ForeignKeyConstraint(["store_id"], ["stores.store_id"]),
            sa.PrimaryKeyConstraint("store_id", "sku"),
        )
    elif "ck_inventory_quantity_non_negative" not in _check_names(inspector, "inventory"):
        op.create_check_constraint(
            "ck_inventory_quantity_non_negative",
            "inventory",
            "quantity >= 0",
        )

    if "inventory_adjustments" not in tables:
        op.create_table(
            "inventory_adjustments",
            sa.Column("request_id", sa.String(length=128), nullable=False),
            sa.Column("store_id", sa.String(length=64), nullable=False),
            sa.Column("sku", sa.String(length=64), nullable=False),
            sa.Column("quantity_delta", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(length=500), nullable=False),
            sa.Column("resulting_quantity", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "quantity_delta <> 0",
                name="ck_inventory_adjustments_delta_non_zero",
            ),
            sa.CheckConstraint(
                "resulting_quantity >= 0",
                name="ck_inventory_adjustments_result_non_negative",
            ),
            sa.ForeignKeyConstraint(["sku"], ["skus.sku"]),
            sa.ForeignKeyConstraint(["store_id"], ["stores.store_id"]),
            sa.PrimaryKeyConstraint("request_id"),
        )
        op.create_index(
            "ix_inventory_adjustments_sku",
            "inventory_adjustments",
            ["sku"],
        )
        op.create_index(
            "ix_inventory_adjustments_store_id",
            "inventory_adjustments",
            ["store_id"],
        )
    else:
        adjustment_checks = _check_names(inspector, "inventory_adjustments")
        if "ck_inventory_adjustments_delta_non_zero" not in adjustment_checks:
            op.create_check_constraint(
                "ck_inventory_adjustments_delta_non_zero",
                "inventory_adjustments",
                "quantity_delta <> 0",
            )
        if "ck_inventory_adjustments_result_non_negative" not in adjustment_checks:
            op.create_check_constraint(
                "ck_inventory_adjustments_result_non_negative",
                "inventory_adjustments",
                "resulting_quantity >= 0",
            )
        adjustment_indexes = _index_names(inspector, "inventory_adjustments")
        if "ix_inventory_adjustments_sku" not in adjustment_indexes:
            op.create_index(
                "ix_inventory_adjustments_sku",
                "inventory_adjustments",
                ["sku"],
            )
        if "ix_inventory_adjustments_store_id" not in adjustment_indexes:
            op.create_index(
                "ix_inventory_adjustments_store_id",
                "inventory_adjustments",
                ["store_id"],
            )


def downgrade() -> None:
    """Remove the initial retail operations schema."""

    op.drop_table("inventory_adjustments")
    op.drop_table("inventory")
    op.drop_table("skus")
    op.drop_table("stores")
