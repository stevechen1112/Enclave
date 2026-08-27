"""
MKA — 製造業知識助理領域模型。

對照 ENGINEERING_PLAN.md §4 的 10 個資料模型：
- JobModule（§4.1）
- TenantModuleBinding（§4.2）
- InteractionSession（§4.3）
- SceneContext（§4.4，嵌入 InteractionSession）
- TenantTermDictionary（§4.5）
- FormDefinition（§4.6）
- FormInstance（§4.7）
- RuleSet（§4.8）
- ApprovalPolicy（§4.9）
- KnowhowCard（§4.10）
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base

# ═══════════════════════════════════════════════════════════════════════════════
#  JobModule（§4.1）— 職能模組定義
# ═══════════════════════════════════════════════════════════════════════════════


class JobModule(Base):
    """職能模組 — 使用者工作能力（不是 sidecar pack）。"""

    __tablename__ = "job_modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    module_key = Column(
        String, nullable=False, index=True
    )  # spec_sop | sales_quote | incident_handover | quality_8d | training_knowhow
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )  # null = 全租戶可用
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String, default="1.0")
    status = Column(String, default="draft")  # draft | enabled | disabled | deprecated
    allowed_roles = Column(JSON, default=list)
    allowed_departments = Column(JSON, default=list)
    # 業務職能 allowlist（JobRole.role_key）；空/NULL = 不限職能（向後相容）
    allowed_job_role_keys = Column(JSON, default=list)
    knowledge_scope_policy = Column(JSON, default=dict)
    supported_intents = Column(JSON, default=list)
    allowed_tools = Column(JSON, default=list)
    form_definition_ids = Column(JSON, default=list)
    approval_policy_id = Column(UUID(as_uuid=True), nullable=True)
    ux_entrypoints = Column(JSON, default=list)
    metrics_config = Column(JSON, default=dict)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("module_key", "tenant_id", name="uq_job_module_key_tenant"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TenantModuleBinding（§4.2）— 租戶模組啟用
# ═══════════════════════════════════════════════════════════════════════════════


class TenantModuleBinding(Base):
    """每家公司啟用不同模組、覆寫公司版型與規則。"""

    __tablename__ = "tenant_module_bindings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    module_key = Column(String, nullable=False, index=True)
    module_version = Column(String, default="1.0")
    enabled = Column(Boolean, default=False)
    license_state = Column(
        String, default="trial"
    )  # trial | active | expired | suspended
    config_json = Column(JSON, default=dict)  # 公司覆寫
    config_version = Column(Integer, default=1, nullable=False, server_default="1")
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", name="uq_tenant_module_binding"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  InteractionSession（§4.3）— 語音/文字/掃碼跨步驟填表
# ═══════════════════════════════════════════════════════════════════════════════


class InteractionSession(Base):
    """互動 session — 不取代 Chat Conversation。"""

    __tablename__ = "interaction_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    module_key = Column(String, nullable=True)
    channel = Column(String, default="web")  # web | pwa | app | line
    scene_context = Column(JSON, default=dict)  # §4.4 SceneContext
    transcript = Column(Text, nullable=True)
    transcript_metadata = Column(
        JSON, default=dict
    )  # provider/language/segments/confidence/duration
    transcript_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    detected_fields = Column(JSON, default=dict)
    pending_questions = Column(JSON, default=list)
    risk_level = Column(String, default="low")  # low | medium | high
    state = Column(
        String, default="active"
    )  # active | waiting_confirmation | completed | expired
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════════════════
#  TenantTermDictionary（§4.5）— 公司專有詞字典
# ═══════════════════════════════════════════════════════════════════════════════


class TenantTermDictionary(Base):
    """公司專有名詞、料號、客戶名、設備代碼、中英混用、常見誤聽。"""

    __tablename__ = "tenant_term_dictionaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    term = Column(String, nullable=False)
    aliases = Column(JSON, default=list)
    phonetic_hints = Column(JSON, default=list)
    category = Column(
        String, default="general"
    )  # part_number | customer | equipment | general
    scope = Column(String, default="global")  # global | module:xxx
    active = Column(Boolean, default=True)
    source = Column(String, nullable=True)  # manual | imported | auto_extracted
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "term", name="uq_tenant_term"),
        Index("ix_tenant_term_category", "tenant_id", "category"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  FormDefinition（§4.6）— 表單定義
# ═══════════════════════════════════════════════════════════════════════════════


class FormDefinition(Base):
    """固定表單 Schema 定義。"""

    __tablename__ = "form_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )  # null = 全租戶
    form_key = Column(
        String, nullable=False, index=True
    )  # quote | purchase_order | incident | ...
    name = Column(String, nullable=False)
    schema_version = Column(String, default="1.0")
    json_schema = Column(JSON, default=dict)  # 欄位型別、required、enum、pattern
    ui_schema = Column(JSON, default=dict)  # 顯示順序、widget、layout
    output_templates = Column(JSON, default=list)  # PDF/Word/Excel 版型
    field_sources = Column(JSON, default=dict)  # 欄位來源：voice|scene|manual|erp|rule
    active_template_id = Column(UUID(as_uuid=True), nullable=True)
    approval_policy_json = Column(JSON, default=dict)
    rule_set_id = Column(UUID(as_uuid=True), nullable=True)
    approval_policy_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String, default="draft")  # draft | active | deprecated
    effective_from = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "form_key",
            "tenant_id",
            "schema_version",
            name="uq_form_def_key_tenant_version",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  FormInstance（§4.7）— 表單實例
# ═══════════════════════════════════════════════════════════════════════════════


class FormInstance(Base):
    """填寫後的表單實例。"""

    __tablename__ = "form_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    form_definition_id = Column(
        UUID(as_uuid=True),
        ForeignKey("form_definitions.id"),
        nullable=False,
        index=True,
    )
    form_version = Column(String, default="1.0")
    module_key = Column(String, nullable=True)
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status = Column(
        String, default="draft"
    )  # draft | pending_review | changes_requested | approved | finalized | void
    record_version = Column(Integer, default=1, nullable=False)  # optimistic locking
    values_json = Column(JSON, default=dict)
    provenance_json = Column(JSON, default=dict)  # 每欄位來源
    calculation_snapshot = Column(JSON, default=dict)  # 計算快照
    validation_result = Column(JSON, default=dict)
    source_document_ids = Column(JSON, default=list)
    scene_context = Column(JSON, default=dict)
    approval_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "mka_approval_requests.id",
            name="fk_form_instance_approval_request",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    immutable_snapshot = Column(JSON, default=dict)
    export_artifacts = Column(JSON, default=list)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    finalized_at = Column(DateTime(timezone=True), nullable=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  RuleSet（§4.8）— 確定性規則引擎
# ═══════════════════════════════════════════════════════════════════════════════


class RuleSet(Base):
    """版本化、可測試的程式/宣告式規則。"""

    __tablename__ = "rule_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    rule_key = Column(
        String, nullable=False, index=True
    )  # pricing | tax | moq | delivery
    version = Column(String, default="1.0")
    input_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)
    implementation_ref = Column(String, nullable=True)  # Python function ref
    test_cases = Column(JSON, default=list)
    status = Column(String, default="draft")  # draft | active | deprecated
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "rule_key", "tenant_id", "version", name="uq_rule_set_key_tenant_version"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ApprovalPolicy（§4.9）— 簽核政策
# ═══════════════════════════════════════════════════════════════════════════════


class ApprovalPolicy(Base):
    """業務簽核政策。"""

    __tablename__ = "approval_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    module_key = Column(String, nullable=True)
    object_type = Column(String, nullable=False)  # form | knowhow | tool
    version = Column(String, default="1.0", nullable=False)
    status = Column(String, default="active")  # draft | active | deprecated
    risk_level = Column(String, default="medium")  # low | medium | high
    steps = Column(JSON, default=list)  # 多級簽核步驟
    timeout_policy = Column(JSON, default=dict)
    delegation_policy = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class MKAApprovalRequest(Base):
    """簽核請求（業務簽核，與 AgentApprovalRequest 分離）。"""

    __tablename__ = "mka_approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    approval_policy_id = Column(
        UUID(as_uuid=True), ForeignKey("approval_policies.id"), nullable=True
    )
    object_type = Column(String, nullable=False)  # form | knowhow | tool
    object_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    policy_version = Column(String, default="1.0")
    current_step = Column(Integer, default=0)
    record_version = Column(Integer, default=1, nullable=False)  # optimistic locking
    status = Column(
        String, default="pending"
    )  # pending | approved | rejected | expired
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String, nullable=False)
    reviewers = Column(JSON, default=list)
    decision_log = Column(JSON, default=list)
    immutable_snapshot = Column(JSON, default=dict)  # 核准後不可修改
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_mka_approval_idempotency"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  KnowhowCard（§4.10）— 知識卡
# ═══════════════════════════════════════════════════════════════════════════════


class KnowhowCardModel(Base):
    """知識卡 DB 模型（與記憶體 KnowhowCard 對應）。"""

    __tablename__ = "knowhow_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )  # 建立者；PATCH/submit 授權依據
    card_id = Column(
        String, nullable=False, index=True
    )  # 與記憶體 KnowhowCard.card_id 對應
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)  # 補上記憶體 KnowhowCard 的 summary
    status = Column(
        String, default="draft"
    )  # draft | pending_review | approved | rejected | retired
    authority_level = Column(
        Integer, default=60
    )  # §7.3 authority: 100/90/80/70/60/20/0
    risk_level = Column(String, default="medium")  # low | medium | high
    applicable_roles = Column(JSON, default=list)
    equipment_ids = Column(JSON, default=list)
    product_ids = Column(JSON, default=list)
    customer_ids = Column(JSON, default=list)
    problem_context = Column(Text, nullable=True)
    recommended_actions = Column(JSON, default=list)
    steps = Column(JSON, default=list)  # 補上記憶體 KnowhowCard 的 steps
    cautions = Column(JSON, default=list)  # 補上記憶體 KnowhowCard 的 cautions
    source_quotes = Column(
        JSON, default=list
    )  # 補上記憶體 KnowhowCard 的 source_quotes
    source_type = Column(String, nullable=True)  # audio | document | manual
    source_document_id = Column(String, nullable=True)
    prerequisites = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    prohibited_actions = Column(JSON, default=list)
    source_audio_uri = Column(Text, nullable=True)
    transcript_id = Column(String, nullable=True)
    interviewee = Column(String, nullable=True)
    interviewer = Column(String, nullable=True)
    reviewer = Column(UUID(as_uuid=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    related_sop_ids = Column(JSON, default=list)
    conflict_report = Column(JSON, default=list)
    version = Column(Integer, default=1)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    review_due_at = Column(DateTime(timezone=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)
    superseded_by_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "card_id", name="uq_knowhow_card_tenant_card"),
        Index("ix_knowhow_tenant_status", "tenant_id", "status"),
    )


# Long-form interview capture ------------------------------------------------
# These records are deliberately separate from InteractionSession.  The latter
# represents a short, confirmable voice command; a capture session has durable
# audio chunks, a resumable upload lifecycle, and a later transcription job.
class KnowledgeCaptureSession(Base):
    __tablename__ = "mka_knowledge_capture_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    title = Column(String, nullable=False)
    equipment_id = Column(String, nullable=True)
    interviewee = Column(String, nullable=True)
    interviewer = Column(String, nullable=True)
    status = Column(String, nullable=False, default="recording", index=True)
    # recording | uploading | queued | transcribing | ready_for_review | failed | aborted
    consent_version = Column(String, nullable=False, default="long-interview-v1")
    consented_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    audio_policy_snapshot = Column(JSON, default=dict)
    transcript_policy_snapshot = Column(JSON, default=dict)
    expected_chunks = Column(Integer, nullable=True)
    received_chunks = Column(Integer, nullable=False, default=0)
    total_duration_ms = Column(Integer, nullable=False, default=0)
    transcript = Column(Text, nullable=True)
    transcript_metadata = Column(JSON, default=dict)
    error = Column(JSON, default=dict)
    audio_expires_at = Column(DateTime(timezone=True), nullable=True)
    transcript_expires_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # Phase B bridge: a completed capture becomes one immutable audio manifest.
    source_asset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    source_asset_revision_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_mka_capture_tenant_source_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_asset_id", "source_asset_revision_id"],
            [
                "asset_revisions.tenant_id",
                "asset_revisions.asset_id",
                "asset_revisions.id",
            ],
            name="fk_mka_capture_tenant_asset_revision",
        ),
        CheckConstraint(
            "source_asset_revision_id IS NULL OR source_asset_id IS NOT NULL",
            name="ck_mka_capture_revision_requires_asset",
        ),
        Index("ix_mka_capture_tenant_owner_status", "tenant_id", "owner_id", "status"),
    )


class KnowledgeCaptureChunk(Base):
    __tablename__ = "mka_knowledge_capture_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mka_knowledge_capture_sessions.id"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False)
    offset_ms = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    storage_key = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    transcription_state = Column(String, nullable=False, default="pending")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "session_id", "sequence", name="uq_mka_capture_chunk_sequence"
        ),
        Index(
            "ix_mka_capture_chunk_session_state", "session_id", "transcription_state"
        ),
    )


class KnowledgeCaptureTranscriptSegment(Base):
    __tablename__ = "mka_knowledge_capture_transcript_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mka_knowledge_capture_sessions.id"),
        nullable=False,
        index=True,
    )
    chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mka_knowledge_capture_chunks.id"),
        nullable=True,
        index=True,
    )
    sequence = Column(Integer, nullable=False)
    speaker = Column(String, nullable=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    raw_text = Column(Text, nullable=False)
    corrected_text = Column(Text, nullable=True)
    corrected_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    corrected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mka_capture_segment_session_sequence", "session_id", "sequence"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  MKAAudioPolicy（§12.1）— 租戶音訊保留政策（DB-backed，取代純記憶體實作）
# ═══════════════════════════════════════════════════════════════════════════════


class MKAAudioPolicy(Base):
    """租戶音訊／轉寫保留政策；無記錄時以預設政策運作。"""

    __tablename__ = "mka_audio_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    save_audio = Column(Boolean, default=False)  # 預設不保存音訊
    save_transcript = Column(Boolean, default=True)  # 預設保存轉寫
    audio_retention_days = Column(Integer, default=90)
    transcript_retention_days = Column(Integer, default=365)
    encrypt_at_rest = Column(Boolean, default=True)
    audit_downloads = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════════════════
#  MKATaskCost（§13.4）— 每任務 COGS 成本記錄
# ═══════════════════════════════════════════════════════════════════════════════


class MKATaskCost(Base):
    """每個完成任務的成本記錄（STT/LLM/embedding/rerank/OCR/source verify/storage）。"""

    __tablename__ = "mka_task_costs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    task_type = Column(
        String, nullable=False, index=True
    )  # stt | tts | form_export | chat | ...
    task_id = Column(String, nullable=True)  # 關聯物件 id（如 session id）
    correlation_id = Column(String, nullable=True)
    stt_cost = Column(Float, default=0.0)
    llm_cost = Column(Float, default=0.0)
    embedding_cost = Column(Float, default=0.0)
    rerank_cost = Column(Float, default=0.0)
    ocr_cost = Column(Float, default=0.0)
    source_verify_cost = Column(Float, default=0.0)
    storage_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)
    details = Column(JSON, default=dict)  # provider／duration／model 等
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  SceneRegistry（§4.4）— opaque QR token → SceneContext DB lookup
# ═══════════════════════════════════════════════════════════════════════════════


class SceneRegistry(Base):
    """Opaque QR token → SceneContext mapping for DB-backed scene resolution."""

    __tablename__ = "mka_scene_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    token = Column(String, nullable=False, index=True)
    site_id = Column(String, nullable=True)
    plant_id = Column(String, nullable=True)
    line_id = Column(String, nullable=True)
    equipment_id = Column(String, nullable=True)
    equipment_model = Column(String, nullable=True)
    work_order_id = Column(String, nullable=True)
    product_id = Column(String, nullable=True)
    part_number = Column(String, nullable=True)
    customer_id = Column(String, nullable=True)
    document_version_scope = Column(String, nullable=True)
    label = Column(String, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "token", name="uq_mka_scene_registry_tenant_token"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  JobRole / UserJobRoleAssignment — 製造業職能（與 User.role 安全角色分離）
# ═══════════════════════════════════════════════════════════════════════════════


class JobRole(Base):
    """製造業職務角色（業務／設備／品保／主管／新人等）。"""

    __tablename__ = "mka_job_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    role_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    department_ids = Column(JSON, default=list)
    default_module_keys = Column(JSON, default=list)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "role_key", name="uq_mka_job_role_tenant_key"),
    )


class UserJobRoleAssignment(Base):
    """使用者可兼任多個職能。"""

    __tablename__ = "mka_user_job_role_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    job_role_id = Column(
        UUID(as_uuid=True), ForeignKey("mka_job_roles.id"), nullable=False, index=True
    )
    department_id = Column(UUID(as_uuid=True), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "job_role_id", name="uq_mka_user_job_role"
        ),
    )


class TaskDefinition(Base):
    """版本化任務定義（職能任務平台重構 Phase 2）。

    一個 task_key 可有多版本並存；runtime 解析最新 enabled 版本。
    """

    __tablename__ = "mka_task_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )  # null = 全域定義
    task_key = Column(
        String, nullable=False, index=True
    )  # ask | quote | incident | handover | quality_8d | interview | training | daily_report
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String, default="1.0", nullable=False)
    status = Column(
        String, default="draft", nullable=False
    )  # draft | enabled | disabled | deprecated
    handler_key = Column(String, nullable=False)  # typed handler 註冊鍵
    module_key = Column(String, nullable=True, index=True)  # 所屬職能模組
    applicable_job_role_keys = Column(JSON, default=list)  # 空 = 不限職能
    input_schema = Column(JSON, default=dict)  # JSON Schema（欄位定義）
    required_capabilities = Column(JSON, default=list)  # 安全能力要求
    approval_policy_id = Column(UUID(as_uuid=True), nullable=True)
    output_bindings = Column(
        JSON, default=list
    )  # [{"kind": "form", "form_key": "quote"}, ...]
    risk_level = Column(String, default="low", nullable=False)  # low | medium | high
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "task_key", "version", name="uq_mka_task_def_key_version"
        ),
    )


class TaskRun(Base):
    """任務執行紀錄 — provenance 與統一狀態機的載體。"""

    __tablename__ = "mka_task_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    task_definition_id = Column(
        UUID(as_uuid=True), ForeignKey("mka_task_definitions.id"), nullable=False
    )
    task_key = Column(String, nullable=False, index=True)
    task_version = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    job_role_id = Column(UUID(as_uuid=True), nullable=True)  # 執行時職能
    module_key = Column(String, nullable=True)
    # 統一狀態機：draft → in_progress → waiting_review → approved/rejected → executed/exported/failed
    status = Column(String, default="draft", nullable=False, index=True)
    input_snapshot = Column(JSON, default=dict)  # 建立時的輸入快照（不可變）
    resolved_context = Column(JSON, default=dict)  # EffectiveJobContext 快照
    field_sources = Column(JSON, default=dict)  # {field: {source, ref, confidence}}
    provenance = Column(
        JSON, default=dict
    )  # 文件/版本/規則/工具/模型/confidence/missing/manual_edits
    error = Column(JSON, nullable=True)  # {code, message, retryable}
    output_refs = Column(JSON, default=dict)  # {form_instance_id, export_id, ...}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_mka_task_run_idem"),
        Index("ix_mka_task_runs_tenant_status", "tenant_id", "status"),
    )


class TaskRunEvent(Base):
    """TaskRun 事件流（Phase 7 可觀測性）：狀態轉換、欄位更新、執行、失敗。"""

    __tablename__ = "mka_task_run_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("mka_task_runs.id"), nullable=False, index=True
    )
    event_type = Column(String, nullable=False, index=True)
    # run_created | transition | field_sources_updated | manual_edit | executed | failed
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mka_task_run_events_tenant_type", "tenant_id", "event_type"),
    )


class FormTemplate(Base):
    """公司上傳的 DOCX／XLSX 版型與欄位映射。"""

    __tablename__ = "mka_form_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    form_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    format = Column(String, nullable=False)  # docx | xlsx
    version = Column(String, default="1.0", nullable=False)
    storage_key = Column(String, nullable=False)
    placeholders = Column(JSON, default=list)
    field_mapping = Column(JSON, default=dict)
    status = Column(
        String, default="draft", nullable=False
    )  # draft | active | superseded | retired
    effective_from = Column(DateTime(timezone=True), nullable=True)
    supersedes_id = Column(UUID(as_uuid=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "form_key", "version", name="uq_mka_form_template_version"
        ),
    )


class MKAWriteRequest(Base):
    """企業系統寫入請求（DB-backed）。"""

    __tablename__ = "mka_write_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    request_id = Column(String, nullable=False, index=True)
    correlation_id = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    target_system = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    risk = Column(String, nullable=False)
    payload = Column(JSON, default=dict)
    payload_hash = Column(String, nullable=False)
    approval_token = Column(String, nullable=True)
    approval_required = Column(Boolean, default=True)
    status = Column(String, default="pending", nullable=False)
    result = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    initiated_by = Column(UUID(as_uuid=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_mka_write_idempotency"
        ),
        UniqueConstraint("tenant_id", "request_id", name="uq_mka_write_request_id"),
    )


class MKAWriteAudit(Base):
    __tablename__ = "mka_write_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    write_request_id = Column(
        UUID(as_uuid=True), ForeignKey("mka_write_requests.id"), nullable=True
    )
    correlation_id = Column(String, nullable=False, index=True)
    request_id = Column(String, nullable=False)
    event = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    target_system = Column(String, nullable=True)
    risk = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class MKAEvent(Base):
    """MKA 使用／品質／商業／治理事件。"""

    __tablename__ = "mka_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    event_type = Column(String, nullable=False, index=True)
    module_key = Column(String, nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    object_type = Column(String, nullable=True)
    object_id = Column(String, nullable=True)
    metrics = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class KnowhowLineage(Base):
    __tablename__ = "mka_knowhow_lineage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    card_id = Column(
        UUID(as_uuid=True), ForeignKey("knowhow_cards.id"), nullable=False, index=True
    )
    audio_uri = Column(String, nullable=True)
    transcript_id = Column(String, nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=True)
    recorded_by = Column(UUID(as_uuid=True), nullable=True)
    duration_seconds = Column(Float, default=0.0)
    retention_policy = Column(String, default="transcript_only")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    consent_obtained = Column(Boolean, default=False)
    consent_at = Column(DateTime(timezone=True), nullable=True)
    consent_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MKAReviewReminder(Base):
    __tablename__ = "mka_review_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    card_id = Column(
        UUID(as_uuid=True), ForeignKey("knowhow_cards.id"), nullable=False, index=True
    )
    card_title = Column(String, nullable=True)
    reviewer_id = Column(UUID(as_uuid=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=False)
    reminder_type = Column(String, default="expiry")
    message = Column(Text, nullable=True)
    sent = Column(Boolean, default=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
