import secrets
import warnings
from typing import List, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Known insecure default keys (must never be used in production) ──
_INSECURE_KEYS = {
    "change_this",
    "change_this_to_a_secure_random_string",
    "CHANGE_THIS_PRODUCTION_SECRET_MIN_32_CHARS",
    "secret",
}


class Settings(BaseSettings):
    APP_NAME: str = "Enclave"
    APP_ENV: str = "development"
    ORGANIZATION_NAME: str = "My Organization"  # 地端組織名稱
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change_this"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    ALGORITHM: str = "HS256"

    # ── First superuser (used by scripts/initial_data.py) ──
    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "admin123"
    
    # CORS
    BACKEND_CORS_ORIGINS: str = ""

    # Core API
    CORE_API_URL: str = "http://localhost:5000"
    CORE_SERVICE_TOKEN: str = ""

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "enclave"
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # OpenAI（用於 Generation 回答生成 + HyDE 查詢擴展）
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"  # Generation 使用的模型
    OPENAI_TEMPERATURE: float = 0.3     # 回答生成溫度（低 = 更精確）
    OPENAI_MAX_TOKENS: int = 1500       # 回答最大 token 數

    # Voyage AI + pgvector
    VOYAGE_API_KEY: str = ""
    VOYAGE_MODEL: str = "voyage-4-lite"
    EMBEDDING_DIMENSION: int = 1024

    # Embedding provider: "voyage" (cloud API) | "ollama" (local, free)
    EMBEDDING_PROVIDER: str = "ollama"
    OLLAMA_EMBED_URL: str = "http://host.docker.internal:11434"
    OLLAMA_EMBED_MODEL: str = "bge-m3"

    # LlamaParse（高品質文檔解析 — 跨頁表格、手寫 OCR、複雜佈局）
    LLAMAPARSE_API_KEY: str = ""
    LLAMAPARSE_ENABLED: bool = True  # 設為 False 可強制使用內建解析器
    LLAMAPARSE_RESULT_TYPE: str = "markdown"
    LLAMAPARSE_LANGUAGE: str = "zh-TW"
    LLAMAPARSE_AUTO_MODE: bool = True
    
    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    
    # Document Processing
    CHUNK_SIZE: int = 1000  # tokens
    CHUNK_OVERLAP: int = 150  # tokens
    TABLE_FULL_CHUNK_MAX_CHARS: int = 20000  # 結構化表格全文 chunk 上限
    MARKDOWN_MIN_SECTION_TOKENS: int = 80
    TEXT_MIN_SECTION_TOKENS: int = 30

    # OCR
    OCR_LANGS: str = "chi_tra+eng"

    # Retrieval
    RETRIEVAL_MODE: str = "hybrid"         # semantic / keyword / hybrid
    RETRIEVAL_MIN_SCORE: float = 0.0       # 最低相似度閾值
    RETRIEVAL_RERANK: bool = True          # 是否啟用重排序
    RETRIEVAL_CACHE_TTL: int = 300         # 快取秒數
    RETRIEVAL_TOP_K: int = 5               # 預設返回數量

    # LLM Provider (llm_provider: openai | gemini | ollama)
    LLM_PROVIDER: str = "openai"           # openai = 呼叫 OpenAI API；gemini = Google Gemini；ollama = 本機 LLM
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    # 資料夾掃描預覽專用 Ollama（輕量摘要，走 host.docker.internal 穿透 Docker）
    OLLAMA_SCAN_URL: str = "http://host.docker.internal:11434"
    OLLAMA_SCAN_MODEL: str = "gemma3:27b"
    # 資料夾掃描摘要 LLM 提供商（ollama | gemini | openai）
    SCAN_LLM_PROVIDER: str = "ollama"         # 無 GPU 時改為 gemini 走雲端
    SCAN_GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"  # 掃描摘要用 Gemini 模型
    SCAN_OPENAI_MODEL: str = "gpt-4o-mini"    # 掃描摘要用 OpenAI 模型
    # 內部任務 LLM（分類、改寫等非使用者面向任務，可用較輕量的本地模型省錢）
    INTERNAL_LLM_PROVIDER: str = "ollama"     # ollama | gemini | openai
    INTERNAL_OLLAMA_MODEL: str = "gemma3:27b"  # 內部任務使用的 Ollama 模型
    INTERNAL_GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"  # 內部任務 Gemini 模型
    INTERNAL_OPENAI_MODEL: str = "gpt-4o-mini"  # 內部任務 OpenAI 模型
    # Gemini（透過 OpenAI 相容端點，無需額外 SDK）
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3-flash-preview"

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_GLOBAL_PER_IP: int = 200
    RATE_LIMIT_PER_USER: int = 60
    RATE_LIMIT_CHAT_PER_USER: int = 20

    # Admin IP Whitelist
    ADMIN_IP_WHITELIST_ENABLED: bool = False
    ADMIN_IP_WHITELIST: str = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    ADMIN_TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

    # Phase 10 — Agent 主動索引設定
    AGENT_WATCH_ENABLED: bool = False       # 是否啟用資料夾監控 Agent
    AGENT_WATCH_FOLDERS: str = ""          # 逗號分隔的監控資料夾路徑
    AGENT_SCAN_INTERVAL: int = 60           # 掃描間隔（秒）
    AGENT_BATCH_HOUR: int = 2               # 排程批次處理時間（凌晨幾點）
    AGENT_MAX_CPU_PERCENT: float = 50.0     # 批次處理 CPU 上限

    # Phase 11 — 內容生成設定
    GENERATION_MAX_TOKENS: int = 3000       # 生成文件最大 token
    GENERATION_TEMPERATURE: float = 0.4     # 生成文件 temperature（略高於問答）

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        """Block startup if critical secrets are insecure in production / staging."""
        if self.APP_ENV in ("production", "staging"):
            # ── SECRET_KEY ──
            if self.SECRET_KEY in _INSECURE_KEYS or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    f"SECRET_KEY is insecure ('{self.SECRET_KEY[:8]}…'). "
                    "Set a strong random key (≥ 32 chars) in .env or environment. "
                    f"Hint: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            # ── Database password ──
            if self.POSTGRES_PASSWORD in ("postgres", ""):
                raise ValueError(
                    "POSTGRES_PASSWORD is set to default 'postgres'. "
                    "Set a strong password in .env or environment."
                )
            # ── Superuser credentials ──
            if self.FIRST_SUPERUSER_EMAIL == "admin@example.com":
                warnings.warn(
                    "FIRST_SUPERUSER_EMAIL is still 'admin@example.com'. "
                    "Consider changing it for production.",
                    UserWarning,
                    stacklevel=2,
                )
            if self.FIRST_SUPERUSER_PASSWORD == "admin123":
                warnings.warn(
                    "FIRST_SUPERUSER_PASSWORD is still the default 'admin123'. "
                    "Set FIRST_SUPERUSER_PASSWORD in .env for production.",
                    UserWarning,
                    stacklevel=2,
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_staging(self) -> bool:
        return self.APP_ENV == "staging"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

settings = Settings()
