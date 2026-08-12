"""Add versioned knowledge sources and pgvector chunks.

Revision ID: 20260811_0004
Revises: 20260811_0003
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0004"
down_revision: str | None = "20260811_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "source_version"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("section", sa.String(length=300), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(dim=256),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "source_version"],
            ["knowledge_sources.source_id", "knowledge_sources.source_version"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_knowledge_chunks_source_version_ordinal",
        "knowledge_chunks",
        ["source_id", "source_version", "ordinal"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_sources")
