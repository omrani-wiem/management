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
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_s: int = 300

    # Whisper
    whisper_model: str = "base"
    whisper_language: str | None = "auto"   # "auto" = détection automatique
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = 200

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
