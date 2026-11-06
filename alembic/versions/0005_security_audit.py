"""Ajouter la piste d'audit des appels API authentifiés.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_actor_created", "audit_events", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_table("audit_events")
