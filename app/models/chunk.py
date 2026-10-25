from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from app.database import Base
import uuid

# Dimension des vecteurs : fixée par la migration 0003 et par le modèle d'embedding par défaut
# (paraphrase-multilingual-MiniLM-L12-v2 = 384). Changer de modèle de dimension différente
# demande une nouvelle migration et une réindexation.
EMBEDDING_DIM = 384

TSV_EXPRESSION = r"to_tsvector('simple', regexp_replace(text, '(\w)-(?=\w)', '\1 ', 'g'))"


class MeetingChunk(Base):
    """Un passage d'une réunion (quelques phrases), indexé pour la recherche sémantique et par mots-clés."""
    __tablename__ = "meeting_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)  # isolation des données
    idx = Column(Integer, nullable=False)
    start_seconds = Column(Float, nullable=True)   # NULL pour les anciennes réunions sans segments horodatés
    end_seconds = Column(Float, nullable=True)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    # Les tirets internes deviennent des espaces : sinon PostgreSQL lit « PO-4821 » comme « po » + l'entier « -4821 »
    # et la recherche de « 4821 » échoue (références, numéros de commande, dates...).
    tsv = Column(TSVECTOR, Computed(TSV_EXPRESSION, persisted=True))

    __table_args__ = (
        Index(
            "ix_meeting_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_meeting_chunks_tsv", "tsv", postgresql_using="gin"),
    )
