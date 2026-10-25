"""index sur tasks.meeting_id (idempotent)

Les bases créées avant Alembic (par l'ancien create_all) n'ont pas cet index : après
`alembic stamp 0001`, cette migration le crée. Sur une base neuve, 0001 l'a déjà créé : sans effet.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_meeting_id ON tasks (meeting_id)")


def downgrade() -> None:
    # l'index appartient à 0001 : c'est elle qui le supprime
    pass
