"""Add versioned analytics batch results.

Revision ID: 20260811_0003
Revises: 20260811_0002
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_runs",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=128), nullable=False),
        sa.Column("input_rows", sa.Integer(), nullable=False),
        sa.Column("anomaly_detector", sa.String(length=200), nullable=False),
        sa.Column("forecaster", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_rows >= 0", name="ck_analytics_runs_input_rows_non_negative"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_analytics_runs_created_at", "analytics_runs", ["created_at"])

    op.create_table(
        "inventory_anomalies",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("trailing_demand", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analytics_runs.run_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "store_id", "sku", "business_date"),
    )
    op.create_index(
        "ix_inventory_anomalies_run_store_sku_date",
        "inventory_anomalies",
        ["run_id", "store_id", "sku", "business_date"],
    )

    op.create_table(
        "demand_forecasts",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("predicted_units", sa.Float(), nullable=False),
        sa.Column("observed_units", sa.Integer(), nullable=False),
        sa.Column("history_size", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "predicted_units >= 0", name="ck_demand_forecasts_prediction_non_negative"
        ),
        sa.CheckConstraint(
            "observed_units >= 0", name="ck_demand_forecasts_observed_non_negative"
        ),
        sa.CheckConstraint(
            "history_size > 0", name="ck_demand_forecasts_history_positive"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analytics_runs.run_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "store_id", "sku", "target_date"),
    )
    op.create_index(
        "ix_demand_forecasts_run_store_sku_date",
        "demand_forecasts",
        ["run_id", "store_id", "sku", "target_date"],
    )


def downgrade() -> None:
    op.drop_table("demand_forecasts")
    op.drop_table("inventory_anomalies")
    op.drop_table("analytics_runs")
