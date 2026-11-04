from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore" : les anciennes variables du .env (MINIO_*...) ne font plus planter l'appli
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    redis_url: str

    # LLM : "groq" (cloud) ou "ollama" (local)
    llm_provider: str = "groq"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_s: int = 300

    # Whisper
    whisper_model: str = "base"
    whisper_language: str | None = "auto"   # "auto" = détection automatique
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # RAG : recherche dans les réunions passées, avec citations
    rag_enabled: bool = True
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # 384 dimensions, FR/EN/AR
    embedding_cache_dir: str | None = None
    rag_chunk_chars: int = 700          # taille cible d'un passage indexé
    rag_top_k: int = 6                  # passages donnés au LLM
    rag_candidates: int = 20            # candidats par méthode (vecteurs / mots-clés) avant fusion
    rag_min_similarity: float = 0.25    # sous ce seuil (et sans mot-clé commun) : refus sans appeler le LLM

    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = 200

    # Jira Cloud : intégration optionnelle, commune aux utilisateurs du serveur
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None

    # Dev uniquement : crée les tables sans Alembic. En production : `alembic upgrade head`.
    auto_create_tables: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
