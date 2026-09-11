"""LIS Core Configuration"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "LIS"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "changeme"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/lis"
    SYLLABUS_DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/lis_syllabus"

    # Valkey/Redis
    VALKEY_URL: str = "redis://localhost:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_AUDIO: str = "lis-audio"
    MINIO_BUCKET_UPLOADS: str = "lis-uploads"
    MINIO_BUCKET_GENERATED: str = "lis-generated"
    MINIO_BUCKET_EXPORTS: str = "lis-exports"
    MINIO_BUCKET_EVAL: str = "lis-eval"

    # Hugging Face
    HF_HOME: str = "/models/huggingface"
    HF_HUB_ENABLE_HF_TRANSFER: bool = True

    # MLflow
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"

    # GPU
    CUDA_VISIBLE_DEVICES: str = "0"
    PYTORCH_CUDA_ALLOC_CONF: str = "max_split_size_mb:128,expandable_segments:True"

    # Model versions (locked by S06)
    ASR_MODEL: str = "whisper-large-v3-turbo"
    ASR_MODEL_REVISION: str = "main"
    ASR_COMPUTE_TYPE: str = "int8_float16"
    EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-0.6B"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_REVISION: str = "main"

    # LLM Ladder
    LLM_TIER1_MODEL: str = "microsoft/Phi-3-mini-4k-instruct"
    LLM_TIER1_QUANTIZATION: str = "awq"
    LLM_TIER2_MODEL: str = "meta-llama/Meta-Llama-3-8B-Instruct"
    LLM_TIER3_MODEL: str = "gpt-4o-mini"
    LLM_TIER4_MODEL: str = "meta-llama/Meta-Llama-3-8B-Instruct"

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318/v1/traces"
    OTEL_SERVICE_NAME: str = "lis"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
