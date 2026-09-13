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
    DATABASE_URL: str = "postgresql+asyncpg://lis:lis_dev@localhost:5434/lis_main"
    SYLLABUS_DATABASE_URL: str = "postgresql+asyncpg://lis:lis_dev@localhost:5435/lis_syllabus"

    # S11: discrete PG-SYLLABUS connection params for the postgres_fdw
    # CREATE SERVER / CREATE USER MAPPING migration (FDW options take
    # individual values, not a connection string). These deliberately use
    # the container-network hostname/port ("pg-syllabus"/5432), NOT the
    # host-mapped values in SYLLABUS_DATABASE_URL (localhost:5435) - the FDW
    # connection happens container-to-container, from inside PG-MAIN.
    SYLLABUS_DB_HOST: str = "pg-syllabus"
    SYLLABUS_DB_PORT: int = 5432
    SYLLABUS_DB_NAME: str = "lis_syllabus"
    SYLLABUS_DB_USER: str = "lis"
    SYLLABUS_DB_PASSWORD: str = "lis_dev"

    # S11 T11.5: dedicated read-only role for the FDW user mapping itself
    # (see docker/postgres/migrations/syllabus/001_syllabus_items.sql). Kept
    # separate from SYLLABUS_DB_USER/PASSWORD (the write-capable "lis" role
    # used by the direct PG-SYLLABUS connection) because GRANT/REVOKE on the
    # local foreign table has no effect on the table owner - real read-only
    # enforcement has to happen via a genuinely restricted remote role.
    SYLLABUS_FDW_USER: str = "lis_fdw_reader"
    SYLLABUS_FDW_PASSWORD: str = "lis_fdw_reader_dev"

    # Valkey/Redis
    VALKEY_URL: str = "redis://localhost:6379/0"

    # Chunk ingestion (S16)
    CHUNK_MAX_SIZE_MB: int = 10
    CHUNK_IDEMPOTENCY_TTL_S: int = 86400
    SSE_HEARTBEAT_INTERVAL_S: int = 30

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
    PRESIGNED_URL_TTL_S: int = 3600

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

    # ASR worker (S19). ASR_MODEL (above, locked by S06) already names the
    # production model id/short-name; ASR_MODEL_NAME exists separately per the
    # S19 spec's env-var contract for the full HF/CT2 model id the worker
    # loads. In practice these should always agree in production - kept as
    # two settings only because the spec names both and other stages already
    # read ASR_MODEL.
    ASR_MODEL_NAME: str = "Systran/faster-whisper-large-v3-turbo"
    ASR_MODEL_QUANTIZATION: str = "float16"
    ASR_DEVICE: str = "cuda"
    ASR_BEAM_SIZE: int = 5
    ASR_LANGUAGE: str = "en"
    ASR_WORD_TIMESTAMPS: bool = True
    ASR_ALIGNMENT_MODEL: str = "jonatasgrosman/wav2vec2-large-xlsr-53-english"
    ASR_MAX_CHUNK_DURATION_S: int = 30
    EMBED_MODEL_VER: str = "qwen3-0.6b-v1"

    # LLM Ladder
    LLM_TIER1_MODEL: str = "microsoft/Phi-3-mini-4k-instruct"
    LLM_TIER1_QUANTIZATION: str = "awq"
    LLM_TIER2_MODEL: str = "meta-llama/Meta-Llama-3-8B-Instruct"
    LLM_TIER3_MODEL: str = "gpt-4o-mini"
    LLM_TIER4_MODEL: str = "meta-llama/Meta-Llama-3-8B-Instruct"

    # Audio pre-processing chain (S17)
    PREPROCESSING_WORKER_CONCURRENCY: int = 1
    VAD_THRESHOLD: float = 0.5
    VAD_MIN_SPEECH_MS: int = 250
    LOUDNORM_TARGET_LUFS: float = -23.0
    LOUDNORM_TP: float = -2.0
    CHAIN_TIMEOUT_S: int = 3
    DEEPFILTER_ENABLED: bool = True
    PREPROCESSING_ENABLED: bool = True

    # Audio quality metrics & warnings (S18)
    QUALITY_SNR_DEGRADED_DB: float = 20.0
    QUALITY_SNR_WARNING_DB: float = 15.0
    QUALITY_SNR_CRITICAL_DB: float = 10.0
    QUALITY_CLIPPING_WARNING: float = 0.01
    QUALITY_CLIPPING_CRITICAL: float = 0.05
    QUALITY_ROLLING_WINDOW_SIZE: int = 5
    QUALITY_MIN_CHUNKS: int = 3
    QUALITY_WARNING_COOLDOWN_S: int = 30
    QUALITY_WARNINGS_ENABLED: bool = True
    QUALITY_SPEECH_RATIO_MIN: float = 0.1

    # Anonymous diarisation (S20)
    DIARISATION_ENABLED: bool = True
    DIARISATION_MODEL: str = "pyannote/speaker-diarization-3.1"
    DIARISATION_MAX_SPEAKERS: int = 5
    NFR_S4_AUDIT_ENABLED: bool = True

    # Dual-ASR ensemble (S21)
    SECONDARY_ASR_MODEL: str = "nvidia/canary-25b-12b-pt"
    SECONDARY_ASR_ENGINE: str = "faster_whisper"
    SECONDARY_ASR_COMPUTE_TYPE: str = "int8_float16"
    SECONDARY_ASR_DEVICE: str = "cuda"
    SECONDARY_ASR_BEAM_SIZE: int = 5
    DUAL_ASR_ENABLED: bool = True
    AGREEMENT_THRESHOLD: float = 0.5

    # Hallucination detection (S22)
    HALLUCINATION_DETECTION_ENABLED: bool = True
    HALLUCINATION_AGREEMENT_THRESHOLD: float = 0.5
    HALLUCINATION_MAX_REPEAT_NGRAM: int = 3
    HALLUCINATION_MAX_REPEAT_COUNT: int = 3
    HALLUCINATION_VAD_MARGIN_MS: int = 200
    HALLUCINATION_MIN_UTTERANCE_LENGTH_MS: int = 500

    # Retry queue (S23)
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_DELAY_SECONDS: int = 60
    RETRY_BACKOFF_MULTIPLIER: float = 2.0

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318/v1/traces"
    OTEL_SERVICE_NAME: str = "lis"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
