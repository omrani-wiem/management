from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore" : les anciennes variables (MINIO_*) du .env ne font plus planter l'appli
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    redis_url: str
    groq_api_key: str

    whisper_model: str = "base"
    whisper_language: str | None = "fr"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = 200

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()