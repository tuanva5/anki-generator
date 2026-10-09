import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PORT: int = 8000
    HOST: str = "127.0.0.1"
    LOCALAI_BASE_URL: str = "http://localhost:8080/v1"
    TEXT_MODEL_NAME: str = "Qwen3.5-9B"
    IMAGE_MODEL_NAME: str = "sd-1.5-ggml"
    TARGET_LANGUAGE: str = "English"
    EXPORT_DECK_NAME: str = "MyDeck"
    OUTPUT_DIR: str = "./exports"
    DB_FILE: str = "./temporary_batch.db"
    GENERATE_IMAGES: bool = True
    # A local model usually serves one request at a time, so keep this low
    GENERATION_CONCURRENCY: int = 1
    MAX_WORDS_PER_REQUEST: int = 100
    MAX_CARDS_PER_BATCH: int = 300
    MAX_UPLOAD_BYTES: int = 1_000_000
    RETENTION_HOURS: int = 24

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
