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
    Column, String, Integer, DateTime, ForeignKey, func,
    Text, JSON, Boolean, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


# ═══════════════════════════════════════════════════════════════════════════════
#  JobModule（§4.1）— 職能模組定義
# ═══════════════════════════════════════════════════════════════════════════════

class JobModule(Base):
    """職能模組 — 使用者工作能力（不是 sidecar pack）。"""
    __tablename__ = "job_modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    module_key = Column(String, nullable=False, index=True)  # spec_sop | sales_quote | incident_handover | quality_8d | training_knowhow
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)  # null = 全租戶可用
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String, default="1.0")
    status = Column(String, default="draft")  # draft | enabled | disabled | deprecated
    allowed_roles = Column(JSON, default=list)
    allowed_departments = Column(JSON, default=list)
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
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    module_key = Column(String, nullable=False, index=True)
    module_version = Column(String, default="1.0")
    enabled = Column(Boolean, default=False)
    license_state = Column(String, default="trial")  # trial | active | expired | suspended
    config_json = Column(JSON, default=dict)  # 公司覆寫
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
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    module_key = Column(String, nullable=True)
    channel = Column(String, default="web")  # web | pwa | app | line
    scene_context = Column(JSON, default=dict)  # §4.4 SceneContext
    transcript = Column(Text, nullable=True)
    transcript_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    detected_fields = Column(JSON, default=dict)
    pending_questions = Column(JSON, default=list)
    risk_level = Column(String, default="low")  # low | medium | high
    state = Column(String, default="active")  # active | waiting_confirmation | completed | expired
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
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    term = Column(String, nullable=False)
    aliases = Column(JSON, default=list)
    phonetic_hints = Column(JSON, default=list)
    category = Column(String, default="general")  # part_number | customer | equipment | general
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
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)  # null = 全租戶
    form_key = Column(String, nullable=False, index=True)  # quote | purchase_order | incident | ...
    name = Column(String, nullable=False)
    schema_version = Column(String, default="1.0")
    json_schema = Column(JSON, default=dict)  # 欄位型別、required、enum、pattern
    ui_schema = Column(JSON, default=dict)  # 顯示順序、widget、layout
    output_templates = Column(JSON, default=list)  # PDF/Word/Excel 版型
    rule_set_id = Column(UUID(as_uuid=True), nullable=True)
    approval_policy_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String, default="draft")  # draft | active | deprecated
    effective_from = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("form_key", "tenant_id", "schema_version", name="uq_form_def_key_tenant_version"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  FormInstance（§4.7）— 表單實例
# ═══════════════════════════════════════════════════════════════════════════════

class FormInstance(Base):
    """填寫後的表單實例。"""
    __tablename__ = "form_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    form_definition_id = Column(UUID(as_uuid=True), ForeignKey("form_definitions.id"), nullable=False, index=True)
    form_version = Column(String, default="1.0")
    module_key = Column(String, nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, default="draft")  # draft | pending_review | changes_requested | approved | finalized | void
    values_json = Column(JSON, default=dict)
    provenance_json = Column(JSON, default=dict)  # 每欄位來源
    calculation_snapshot = Column(JSON, default=dict)  # 計算快照
    validation_result = Column(JSON, default=dict)
    source_document_ids = Column(JSON, default=list)
    scene_context = Column(JSON, default=dict)
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
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    rule_key = Column(String, nullable=False, index=True)  # pricing | tax | moq | delivery
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
        UniqueConstraint("rule_key", "tenant_id", "version", name="uq_rule_set_key_tenant_version"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ApprovalPolicy（§4.9）— 簽核政策
# ═══════════════════════════════════════════════════════════════════════════════

class ApprovalPolicy(Base):
    """業務簽核政策。"""
    __tablename__ = "approval_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    module_key = Column(String, nullable=True)
    object_type = Column(String, nullable=False)  # form | knowhow | tool
    risk_level = Column(String, default="medium")  # low | medium | high
    steps = Column(JSON, default=list)  # 多級簽核步驟
    timeout_policy = Column(JSON, default=dict)
    delegation_policy = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ApprovalRequest(Base):
    """簽核請求（業務簽核，與 AgentApprovalRequest 分離）。"""
    __tablename__ = "mka_approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    object_type = Column(String, nullable=False)  # form | knowhow | tool
    object_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    policy_version = Column(String, default="1.0")
    current_step = Column(Integer, default=0)
    status = Column(String, default="pending")  # pending | approved | rejected | expired
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reviewers = Column(JSON, default=list)
    decision_log = Column(JSON, default=list)
    immutable_snapshot = Column(JSON, default=dict)  # 核准後不可修改
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════════════════
#  KnowhowCard（§4.10）— 知識卡
# ═══════════════════════════════════════════════════════════════════════════════

class KnowhowCardModel(Base):
    """知識卡 DB 模型（與記憶體 KnowhowCard 對應）。"""
    __tablename__ = "knowhow_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    status = Column(String, default="draft")  # draft | pending_review | approved | rejected | retired
    authority_level = Column(Integer, default=60)  # §7.3 authority: 100/90/80/70/60/20/0
    applicable_roles = Column(JSON, default=list)
    equipment_ids = Column(JSON, default=list)
    product_ids = Column(JSON, default=list)
    customer_ids = Column(JSON, default=list)
    problem_context = Column(Text, nullable=True)
    recommended_actions = Column(JSON, default=list)
    prerequisites = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    prohibited_actions = Column(JSON, default=list)
    source_audio_uri = Column(Text, nullable=True)
    transcript_id = Column(String, nullable=True)
    interviewee = Column(String, nullable=True)
    interviewer = Column(String, nullable=True)
    reviewer = Column(UUID(as_uuid=True), nullable=True)
    related_sop_ids = Column(JSON, default=list)
    conflict_report = Column(JSON, default=list)
    version = Column(Integer, default=1)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())