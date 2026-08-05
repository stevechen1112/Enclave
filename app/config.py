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
    FIRST_SUPERUSER_PASSWORD: str = ""  # Must be set via FIRST_SUPERUSER_PASSWORD in .env
    
    # CORS
    BACKEND_CORS_ORIGINS: str = ""

    # Core API
    CORE_API_URL: str = "http://localhost:5000"
    CORE_SERVICE_TOKEN: str = ""
    # Gateway → sidecar 短效 service token TTL（秒）
    SERVICE_TOKEN_TTL_SECONDS: int = 300
    # 可選 mTLS client 憑證（生產建議啟用）
    MTLS_CLIENT_CERT: str = ""
    MTLS_CLIENT_KEY: str = ""
    MTLS_CA_CERT: str = ""

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
    OPENAI_MODEL: str = "gpt-5.6-luna"  # 問答／生成主模型（可被 .env 覆寫）
    OPENAI_TEMPERATURE: float = 0.3     # 回答生成溫度（低 = 更精確）
    OPENAI_MAX_TOKENS: int = 4000       # gpt-5 系含 reasoning；過低會吃光額度導致空回答

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
    
    # File Storage（ADR-011：StorageBackend 抽象）
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    STORAGE_BACKEND: str = "local"  # local | s3（R2／Linode Objects／MinIO 皆走 s3）
    S3_ENDPOINT_URL: str = ""  # 空字串 = AWS S3 預設端點
    S3_BUCKET: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "auto"
    S3_PRESIGN_EXPIRES: int = 3600
    STORAGE_DELETE_ON_REVOKE: bool = False  # 撤權時是否實體刪除物件（預設保留 tombstone 行為）

    # Tenant RLS（ADR-012）：false=shadow（policy 已建、owner 不受 FORCE 約束）；
    # true=enforce（migration 需以同名環境變數重跑才會 FORCE ROW LEVEL SECURITY）
    RLS_ENFORCEMENT_ENABLED: bool = False
    
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

    # P0-1：Parent Document / Sibling Expansion / Context Fitting
    # 借鑑 OpenDocuments 的 parent-doc.ts / retriever.ts / context-window.ts
    # 預設關閉，需通過 ablation 證明增量後才開啟
    PARENT_DOC_ENABLED: bool = False          # 命中 chunk 後，若 parent_chunk_id 非空，改回傳 parent text
    SIBLING_EXPANSION_ENABLED: bool = False   # 命中 chunk 後，附加相鄰 chunk_index ± 1 的 sibling
    SIBLING_EXPANSION_WINDOW: int = 1          # 每側擴展幾個 sibling（1 = 前後各 1 個）
    SIBLING_SCORE_DISCOUNT: float = 0.85      # sibling 的 score 乘以此折扣（避免 sibling 壓過原始命中）
    CONTEXT_FITTING_ENABLED: bool = False      # 依 token 預算裁切 context，避免 parent/sibling 擴展後超窗
    CONTEXT_FITTING_TOKEN_BUDGET: int = 6000   # context 總 token 預算（不含 citation 標記）
    CONTEXT_FITTING_MODEL: str = "voyage-4-lite"  # tokenizer 估算用模型名（僅作粗估）

    # Source-grounded 逐字溯源驗證（生成之後、輸出之前的稽核層）
    # off    = 不驗證（現行行為）
    # shadow = 照常輸出，事後稽核並記錄（收集數據用，不影響使用者）
    # enforce = 先緩衝回答，通過稽核才輸出；失敗則約束式重新生成一次，再失敗則結構化拒答
    SOURCE_VERIFY_MODE: str = "off"
    SOURCE_VERIFY_USE_INTERNAL_LLM: bool = True  # 稽核走內部 LLM（本地 Ollama），失敗退回主 LLM
    SOURCE_VERIFY_MODEL: str = ""  # 稽核專用模型覆寫；空字串 = 沿用內部模型設定

    # ── P1：製造業產品工作層 ──
    # Voice / STT / TTS Interaction Gateway（稽核文件 §6.7、§10 P1）
    # 借鑑 WeKnora ASR 入庫 pipeline，但 Enclave 自建 voice-first Interaction Gateway
    VOICE_STT_ENABLED: bool = False          # 語音轉文字（STT）入口
    VOICE_TTS_ENABLED: bool = False          # 文字轉語音（TTS）輸出
    VOICE_STT_PROVIDER: str = "openai"       # openai | azure | local
    VOICE_TTS_PROVIDER: str = "openai"       # openai | azure | local
    VOICE_STT_MODEL: str = "whisper-1"        # OpenAI Whisper model name
    VOICE_TTS_MODEL: str = "tts-1"           # OpenAI TTS model name
    VOICE_TTS_VOICE: str = "alloy"            # OpenAI TTS voice
    VOICE_MAX_AUDIO_SECONDS: int = 120       # 單次語音輸入上限（秒）
    VOICE_DRAFT_FIRST: bool = True           # 音訊轉寫先進 draft，不可直接回答（§6.8 驗收）

    # Fixed Form Schema（稽核文件 §11.3）
    # 完成不等於 LLM 生成 Markdown，而是 schema + required fields + deterministic calculations
    FIXED_FORM_ENABLED: bool = False
    FIXED_FORM_REQUIRE_APPROVAL: bool = True  # 正式表單需簽核
    FIXED_FORM_VERSIONED: bool = True        # 表單版本化

    # Agent runtime（稽核文件 §6.3、§6.5）
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_APPROVAL_TIMEOUT_HOURS: int = 24
    AGENT_APPROVAL_ESCALATION_HOURS: int = 48
    AGENT_APPROVAL_REQUIRE_FOR_MUTATING: bool = True  # mutating tool 預設需 approval（§6.8）

    # 職能模組 Router（稽核文件 §10 P1）
    MODULE_ROUTER_ENABLED: bool = False

    # ── CG-AUTH-SSO：email 驗證與 MFA ──
    # 開啟後，email_verified=false 的用戶不可聊天（其餘 API 不受限）
    EMAIL_VERIFICATION_ENABLED: bool = False
    # 開啟後，owner 角色登入未完成 MFA 設定前只核發 mfa_enroll 局部 token
    MFA_ENFORCE_OWNER: bool = False
    MFA_PARTIAL_TOKEN_MINUTES: int = 10  # mfa_pending / mfa_enroll 局部 token 效期
    # SMTP（未設定主機時，驗證信退化為寫 log——開發模式；生產必須設定）
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@enclave.local"
    SMTP_USE_TLS: bool = True
    FRONTEND_BASE_URL: str = "http://localhost:3000"  # 組驗證連結用
    BACKEND_BASE_URL: str = "http://localhost:8000"  # 金流 NotifyURL 等 webhook

    # ── CG-PAY：NewebPay 藍新金流 ──
    NEWEBPAY_MERCHANT_ID: str = ""
    NEWEBPAY_HASH_KEY: str = ""
    NEWEBPAY_HASH_IV: str = ""
    NEWEBPAY_TEST_MODE: bool = True

    # ── CG-OBS：Sentry + Langfuse ──
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.0
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # ── CG-CLAMAV：上傳掃毒（SaaS／託管 fail-closed；地端預設關閉）──
    CLAMAV_ENABLED: bool = False
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT_SECONDS: int = 30
    CLAMAV_FAIL_CLOSED: bool = True  # 掃毒服務不可用時拒絕上傳

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

    # Rate Limiting（三層：IP／user／tenant；production/staging 啟用 user+tenant）
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_GLOBAL_PER_IP: int = 200
    RATE_LIMIT_PER_USER: int = 60
    RATE_LIMIT_PER_TENANT: int = 300
    RATE_LIMIT_CHAT_PER_USER: int = 20
    # 聊天配額預留：每次 reserve 先計入 estimated token，finalize 時改為實際值
    CHAT_TOKEN_RESERVE_ESTIMATE: int = 4000

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
            if not self.FIRST_SUPERUSER_PASSWORD:
                warnings.warn(
                    "FIRST_SUPERUSER_PASSWORD is empty. "
                    "Set FIRST_SUPERUSER_PASSWORD in .env before first run.",
                    UserWarning,
                    stacklevel=2,
                )
            # ── Admin whitelist (must be enabled in production/staging) ──
            if not self.ADMIN_IP_WHITELIST_ENABLED:
                raise ValueError(
                    "ADMIN_IP_WHITELIST_ENABLED must be true in production/staging. "
                    "Set ADMIN_IP_WHITELIST_ENABLED=true and configure ADMIN_IP_WHITELIST."
                )
            # ── CG-CLAMAV：SaaS／託管必須啟用掃毒 ──
            if self.CLAMAV_FAIL_CLOSED and not self.CLAMAV_ENABLED:
                raise ValueError(
                    "CLAMAV_ENABLED must be true when CLAMAV_FAIL_CLOSED=true in production/staging."
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
