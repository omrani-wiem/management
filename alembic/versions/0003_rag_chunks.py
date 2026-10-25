"""RAG : extension pgvector et table des passages indexés (vecteurs + mots-clés)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 21:07:04.915439

"""
from typing import Sequence, Union

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# identique à app.models.chunk.TSV_EXPRESSION (copiée ici : une migration ne doit pas changer si le code change)
TSV_EXPRESSION = r"to_tsvector('simple', regexp_replace(text, '(\w)-(?=\w)', '\1 ', 'g'))"


def upgrade() -> None:
    """Upgrade schema."""
    # nécessite l'image pgvector/pgvector (docker compose) ou l'extension installée sur le serveur
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('meeting_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('meeting_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('idx', sa.Integer(), nullable=False),
    sa.Column('start_seconds', sa.Float(), nullable=True),
    sa.Column('end_seconds', sa.Float(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed(TSV_EXPRESSION, persisted=True), nullable=True),
    sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_meeting_chunks_embedding', 'meeting_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index(op.f('ix_meeting_chunks_meeting_id'), 'meeting_chunks', ['meeting_id'], unique=False)
    op.create_index(op.f('ix_meeting_chunks_owner_id'), 'meeting_chunks', ['owner_id'], unique=False)
    op.create_index('ix_meeting_chunks_tsv', 'meeting_chunks', ['tsv'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    """Downgrade schema (l'extension reste installée : d'autres bases peuvent l'utiliser)."""
    op.drop_index('ix_meeting_chunks_tsv', table_name='meeting_chunks', postgresql_using='gin')
    op.drop_index(op.f('ix_meeting_chunks_owner_id'), table_name='meeting_chunks')
    op.drop_index(op.f('ix_meeting_chunks_meeting_id'), table_name='meeting_chunks')
    op.drop_index('ix_meeting_chunks_embedding', table_name='meeting_chunks', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('meeting_chunks')
