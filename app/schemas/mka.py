"""
MKA Pydantic schemas — API 合約定義。

對照 ENGINEERING_PLAN.md §4 的領域模型，定義 API 層的 request/response schema。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── JobModule（§4.1）──

class JobModuleBase(BaseModel):
    module_key: str = Field(..., description="spec_sop | sales_quote | incident_handover | quality_8d | training_knowhow")
    name: str
    description: Optional[str] = None
    version: str = "1.0"
    status: str = "draft"
    allowed_roles: List[str] = Field(default_factory=list)
    allowed_departments: List[str] = Field(default_factory=list)
    knowledge_scope_policy: Dict[str, Any] = Field(default_factory=dict)
    supported_intents: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(default_factory=list)
    form_definition_ids: List[str] = Field(default_factory=list)
    ux_entrypoints: List[str] = Field(default_factory=list)
    metrics_config: Dict[str, Any] = Field(default_factory=dict)


class JobModuleCreate(JobModuleBase):
    pass


class JobModuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    allowed_roles: Optional[List[str]] = None
    allowed_departments: Optional[List[str]] = None
    knowledge_scope_policy: Optional[Dict[str, Any]] = None
    supported_intents: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    form_definition_ids: Optional[List[str]] = None
    ux_entrypoints: Optional[List[str]] = None
    metrics_config: Optional[Dict[str, Any]] = None


class JobModuleResponse(JobModuleBase):
    id: UUID
    tenant_id: Optional[UUID] = None
    approval_policy_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── TenantModuleBinding（§4.2）──

class TenantModuleBindingBase(BaseModel):
    module_key: str
    module_version: str = "1.0"
    enabled: bool = False
    license_state: str = "trial"
    config_json: Dict[str, Any] = Field(default_factory=dict)


class TenantModuleBindingCreate(TenantModuleBindingBase):
    pass


class TenantModuleBindingResponse(TenantModuleBindingBase):
    id: UUID
    tenant_id: UUID
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── InteractionSession（§4.3）──

class InteractionSessionCreate(BaseModel):
    module_key: Optional[str] = None
    channel: str = "web"
    scene_context: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"


class InteractionSessionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    module_key: Optional[str] = None
    channel: str = "web"
    scene_context: Dict[str, Any] = Field(default_factory=dict)
    transcript: Optional[str] = None
    transcript_confirmed_at: Optional[datetime] = None
    detected_fields: Dict[str, Any] = Field(default_factory=dict)
    pending_questions: List[Any] = Field(default_factory=list)
    risk_level: str = "low"
    state: str = "active"
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TranscriptUpdate(BaseModel):
    transcript: str
    confirmed: bool = False


# ── SceneContext（§4.4）──

class SceneResolveRequest(BaseModel):
    qr_token: Optional[str] = None
    barcode: Optional[str] = None


class SceneContextResponse(BaseModel):
    site_id: Optional[str] = None
    plant_id: Optional[str] = None
    line_id: Optional[str] = None
    equipment_id: Optional[str] = None
    equipment_model: Optional[str] = None
    work_order_id: Optional[str] = None
    product_id: Optional[str] = None
    part_number: Optional[str] = None
    customer_id: Optional[str] = None
    document_version_scope: Optional[str] = None
    resolved_from: str = "user"
    resolved_at: Optional[str] = None


# ── TenantTermDictionary（§4.5）──

class TermDictionaryCreate(BaseModel):
    term: str
    aliases: List[str] = Field(default_factory=list)
    phonetic_hints: List[str] = Field(default_factory=list)
    category: str = "general"
    scope: str = "global"
    source: Optional[str] = None


class TermDictionaryResponse(TermDictionaryCreate):
    id: UUID
    tenant_id: UUID
    active: bool = True
    last_verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── FormDefinition（§4.6）──

class FormDefinitionBase(BaseModel):
    form_key: str
    name: str
    schema_version: str = "1.0"
    json_schema: Dict[str, Any] = Field(default_factory=dict)
    ui_schema: Dict[str, Any] = Field(default_factory=dict)
    output_templates: List[Any] = Field(default_factory=list)
    status: str = "draft"


class FormDefinitionCreate(FormDefinitionBase):
    pass


class FormDefinitionResponse(FormDefinitionBase):
    id: UUID
    tenant_id: Optional[UUID] = None
    rule_set_id: Optional[UUID] = None
    approval_policy_id: Optional[UUID] = None
    effective_from: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── FormInstance（§4.7）──

class FormInstanceCreate(BaseModel):
    form_definition_id: UUID
    module_key: Optional[str] = None
    values: Dict[str, Any] = Field(default_factory=dict)
    source_document_ids: List[str] = Field(default_factory=list)
    scene_context: Dict[str, Any] = Field(default_factory=dict)


class FormInstancePatch(BaseModel):
    values: Optional[Dict[str, Any]] = None
    provenance: Optional[Dict[str, Any]] = None
    source_document_ids: Optional[List[str]] = None


class FormInstanceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    form_definition_id: UUID
    form_version: str = "1.0"
    module_key: Optional[str] = None
    owner_id: UUID
    status: str = "draft"
    values_json: Dict[str, Any] = Field(default_factory=dict)
    provenance_json: Dict[str, Any] = Field(default_factory=dict)
    calculation_snapshot: Dict[str, Any] = Field(default_factory=dict)
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    source_document_ids: List[Any] = Field(default_factory=list)
    scene_context: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    finalized_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FormCalculateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class FormCalculateResponse(BaseModel):
    calculated_fields: Dict[str, Any] = Field(default_factory=dict)
    calculation_snapshot: Dict[str, Any] = Field(default_factory=dict)


class FormValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)


class FormSubmitResponse(BaseModel):
    instance_id: UUID
    status: str
    approval_request_id: Optional[UUID] = None


# ── RuleSet（§4.8）──

class RuleSetBase(BaseModel):
    rule_key: str
    version: str = "1.0"
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    implementation_ref: Optional[str] = None
    test_cases: List[Any] = Field(default_factory=list)
    status: str = "draft"


class RuleSetCreate(RuleSetBase):
    pass


class RuleSetResponse(RuleSetBase):
    id: UUID
    tenant_id: Optional[UUID] = None
    approved_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── ApprovalPolicy（§4.9）──

class ApprovalPolicyBase(BaseModel):
    module_key: Optional[str] = None
    object_type: str
    risk_level: str = "medium"
    steps: List[Any] = Field(default_factory=list)
    timeout_policy: Dict[str, Any] = Field(default_factory=dict)
    delegation_policy: Dict[str, Any] = Field(default_factory=dict)


class ApprovalPolicyCreate(ApprovalPolicyBase):
    pass


class ApprovalPolicyResponse(ApprovalPolicyBase):
    id: UUID
    tenant_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── MKAApprovalRequest（§4.9）──

class ApprovalDecisionRequest(BaseModel):
    reason: str = ""
    changes_requested: Optional[Dict[str, Any]] = None


class ApprovalRequestResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    object_type: str
    object_id: UUID
    policy_version: str = "1.0"
    current_step: int = 0
    status: str = "pending"
    submitted_by: UUID
    reviewers: List[Any] = Field(default_factory=list)
    decision_log: List[Any] = Field(default_factory=list)
    immutable_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── KnowhowCard（§4.10）──

class KnowhowCardCreate(BaseModel):
    title: str
    summary: str = ""
    steps: List[str] = Field(default_factory=list)
    applicable_equipment: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    source_quotes: List[str] = Field(default_factory=list)
    source_type: str = "manual"
    source_document_id: str = ""
    risk_level: str = "medium"
    authority_level: int = 60


class KnowhowCardUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    steps: Optional[List[str]] = None
    applicable_equipment: Optional[List[str]] = None
    cautions: Optional[List[str]] = None
    source_quotes: Optional[List[str]] = None


class KnowhowCardResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    card_id: Optional[str] = None
    title: str
    summary: Optional[str] = None
    status: str = "draft"
    authority_level: int = 60
    steps: List[Any] = Field(default_factory=list)
    cautions: List[Any] = Field(default_factory=list)
    source_quotes: List[Any] = Field(default_factory=list)
    source_type: Optional[str] = None
    source_document_id: Optional[str] = None
    reviewer: Optional[UUID] = None
    version: int = 1
    conflict_report: List[Any] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Bootstrap 擴充（§5.4）──

class InteractionCapabilities(BaseModel):
    voice: bool = False
    camera: bool = False
    qr: bool = False
    offline: bool = False


class BootstrapJobModules(BaseModel):
    job_modules: List[JobModuleResponse] = Field(default_factory=list)
    default_job_home: str = "ask"
    interaction_capabilities: InteractionCapabilities = Field(default_factory=InteractionCapabilities)