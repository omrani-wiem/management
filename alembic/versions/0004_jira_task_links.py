"""Ajouter les liens Jira aux tâches.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("jira_issue_key", sa.String(length=32), nullable=True))
    op.add_column("tasks", sa.Column("jira_issue_url", sa.String(length=500), nullable=True))
    op.add_column("tasks", sa.Column("jira_status", sa.String(length=100), nullable=True))
    op.create_unique_constraint("uq_tasks_jira_issue_key", "tasks", ["jira_issue_key"])


def downgrade() -> None:
    op.drop_constraint("uq_tasks_jira_issue_key", "tasks", type_="unique")
    op.drop_column("tasks", "jira_status")
    op.drop_column("tasks", "jira_issue_url")
    op.drop_column("tasks", "jira_issue_key")
