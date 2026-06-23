from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    redis_url: str
    groq_api_key: str
    whisper_model: str = "base"

    class Config:
        env_file = ".env"

settings = Settings()
