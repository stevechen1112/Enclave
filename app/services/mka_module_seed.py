"""Seed first-party MKA job modules + default job roles."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

CANONICAL_MODULES: List[Dict[str, Any]] = [
    {
        "module_key": "spec_sop",
        "name": "規格與 SOP",
        "description": "產品／設備／版本 scoped 規格查詢、差異比對、步驟 checklist",
        "allowed_roles": ["owner", "admin", "employee"],
        "knowledge_scope_policy": {"doc_types": ["sop", "spec"], "require_version": True},
        "supported_intents": ["lookup_spec", "compare_versions", "sop_steps"],
        "allowed_tools": ["retrieve_sop", "diff_versions", "checklist_from_steps"],
        "form_definition_ids": [],
        "ux_entrypoints": [{"key": "ask_sop", "label": "查規格／SOP", "path": "/ask?module=spec_sop"}],
        "metrics_config": {"track": ["task_completion", "evidence_gaps"]},
        "default_config": {
            "require_version_citation": True,
            "max_context_chunks": 8,
        },
    },
    {
        "module_key": "sales_quote",
        "name": "業務報價",
        "description": "語音開單、規格／歷史報價／MOQ／交期工具、公司版型預覽",
        "allowed_roles": ["owner", "admin", "employee"],
        "knowledge_scope_policy": {"doc_types": ["quote", "price_policy", "spec"]},
        "supported_intents": ["create_quote", "lookup_price", "check_moq"],
        "allowed_tools": ["price_lookup", "moq_check", "lead_time", "history_quotes"],
        "form_definition_ids": ["quote"],
        "ux_entrypoints": [{"key": "open_quote", "label": "開報價單", "path": "/job/tasks/quote"}],
        "metrics_config": {"track": ["quote_time", "field_accuracy", "voice_ratio"]},
        "default_config": {
            "require_approval": True,
            "tax_rate": 5,
            "default_payment_terms": "月結30天",
            "high_risk_fields": ["unit_price", "total", "tax"],
            "quote_valid_days": 30,
        },
    },
    {
        "module_key": "incident_handover",
        "name": "現場異常與交接",
        "description": "掃碼限定設備知識、瑕疵附件、安全指引、維修與交接待辦",
        "allowed_roles": ["owner", "admin", "employee"],
        "knowledge_scope_policy": {"doc_types": ["incident", "maintenance", "safety"], "require_equipment": True},
        "supported_intents": ["report_incident", "handover", "safety_guidance"],
        "allowed_tools": ["equipment_scope", "safety_checklist", "history_cases"],
        "form_definition_ids": ["incident_report", "shift_handover", "equipment_repair", "daily_report"],
        "ux_entrypoints": [
            {"key": "incident", "label": "異常回報", "path": "/job/tasks/incident"},
            {"key": "handover", "label": "交接班", "path": "/job/tasks/handover"},
            {"key": "daily_report", "label": "工作日報", "path": "/job/tasks/daily_report"},
            {"key": "repair", "label": "設備維修", "path": "/forms/equipment_repair"},
        ],
        "metrics_config": {"track": ["incident_time", "safety_acks"]},
        "default_config": {
            "require_scene_for_incident": False,
            "safety_first_prompt": True,
            "high_risk_fields": ["severity", "equipment_id"],
        },
    },
    {
        "module_key": "quality_8d",
        "name": "品保 8D／CAPA",
        "description": "客訴附件、檢驗規格、8D／CAPA、責任人與期限",
        "allowed_roles": ["owner", "admin", "employee"],
        "knowledge_scope_policy": {"doc_types": ["quality", "inspection", "capa"]},
        "supported_intents": ["create_8d", "capa_followup"],
        "allowed_tools": ["inspection_spec", "assign_owner"],
        "form_definition_ids": ["quality_8d", "capa"],
        "ux_entrypoints": [
            {"key": "8d", "label": "8D／CAPA", "path": "/job/tasks/quality_8d"},
        ],
        "metrics_config": {"track": ["open_capa", "due_breaches"]},
        "default_config": {
            "require_approval": True,
            "default_due_days": 14,
            "high_risk_fields": ["root_cause", "corrective_action"],
        },
    },
    {
        "module_key": "training_knowhow",
        "name": "知識傳承與訓練",
        "description": "訪談建卡、職務必讀、情境測驗、完成度追蹤",
        "allowed_roles": ["owner", "admin", "employee"],
        "knowledge_scope_policy": {"doc_types": ["knowhow", "training", "sop"]},
        "supported_intents": ["interview", "training_checklist", "quiz"],
        "allowed_tools": ["interview_extract", "training_progress"],
        "form_definition_ids": ["training_checklist", "meeting_visit"],
        "ux_entrypoints": [
            {"key": "knowhow", "label": "師傅經驗", "path": "/knowhow"},
            {"key": "training", "label": "新人訓練", "path": "/job/tasks/training"},
            {"key": "interview", "label": "訪談建卡", "path": "/job/tasks/interview"},
        ],
        "metrics_config": {"track": ["training_completion", "conflict_resolution_time"]},
        "default_config": {
            "interview_consent_required": True,
            "review_reminder_days": 90,
        },
    },
]


def canonical_default_config(module_key: str) -> Dict[str, Any]:
    """正式模組的預設 config（版本化 merge 的 base）。"""
    for spec in CANONICAL_MODULES:
        if spec["module_key"] == module_key:
            return dict(spec.get("default_config") or {})
    return {}


# ── 正式任務定義（Phase 2：版本化 TaskDefinition 的全域種子）──────────────────

CANONICAL_TASKS: List[Dict[str, Any]] = [
    {
        "task_key": "quote",
        "name": "開報價單",
        "handler_key": "quote",
        "module_key": "sales_quote",
        "applicable_job_role_keys": ["sales", "supervisor"],
        "required_capabilities": ["field_work"],
        "risk_level": "medium",
        "output_bindings": [{"kind": "form", "form_key": "quote"}],
        "input_schema": {
            "type": "object",
            "properties": {
                "values": {"type": "object"},
                "sources": {"type": "object"},
            },
        },
    },
    {
        "task_key": "incident",
        "name": "異常回報",
        "handler_key": "incident",
        "module_key": "incident_handover",
        "applicable_job_role_keys": ["field", "equipment", "quality", "supervisor"],
        "required_capabilities": ["field_work"],
        "risk_level": "high",
        "output_bindings": [{"kind": "form", "form_key": "incident_report"}],
        "input_schema": {"type": "object", "properties": {"values": {"type": "object"}}},
    },
    {
        "task_key": "handover",
        "name": "交接班紀錄",
        "handler_key": "handover",
        "module_key": "incident_handover",
        "applicable_job_role_keys": ["field", "equipment", "supervisor"],
        "required_capabilities": ["field_work"],
        "risk_level": "low",
        "output_bindings": [{"kind": "form", "form_key": "shift_handover"}],
        "input_schema": {"type": "object", "properties": {"values": {"type": "object"}}},
    },
    {
        "task_key": "quality_8d",
        "name": "品質 8D 報告",
        "handler_key": "quality_8d",
        "module_key": "quality_8d",
        "applicable_job_role_keys": ["quality", "supervisor"],
        "required_capabilities": ["field_work"],
        "risk_level": "medium",
        "output_bindings": [{"kind": "form", "form_key": "quality_8d"}],
        "input_schema": {"type": "object", "properties": {"values": {"type": "object"}}},
    },
    {
        "task_key": "interview",
        "name": "師傅訪談",
        "handler_key": "interview",
        "module_key": "training_knowhow",
        "applicable_job_role_keys": ["master", "supervisor"],
        "required_capabilities": ["create_content"],
        "risk_level": "low",
        "output_bindings": [{"kind": "knowhow"}],
        "input_schema": {
            "type": "object",
            "required": ["title", "summary", "steps"],
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "steps": {"type": "array"},
            },
        },
    },
    {
        "task_key": "ask",
        "name": "問知識庫",
        "handler_key": "ask",
        "module_key": "spec_sop",
        "applicable_job_role_keys": [],
        "required_capabilities": ["ask"],
        "risk_level": "low",
        "output_bindings": [],
        "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}},
    },
    {
        "task_key": "training",
        "name": "新人訓練",
        "handler_key": "training",
        "module_key": "training_knowhow",
        "applicable_job_role_keys": ["newcomer", "supervisor"],
        "required_capabilities": ["field_work"],
        "risk_level": "low",
        "output_bindings": [{"kind": "form", "form_key": "training_checklist"}],
        "input_schema": {"type": "object"},
    },
    {
        "task_key": "daily_report",
        "name": "工作日報",
        "handler_key": "daily_report",
        "module_key": "incident_handover",
        "applicable_job_role_keys": ["field", "equipment", "supervisor"],
        "required_capabilities": ["field_work"],
        "risk_level": "low",
        "output_bindings": [{"kind": "form", "form_key": "daily_report"}],
        "input_schema": {"type": "object", "properties": {"values": {"type": "object"}}},
    },
]


def seed_canonical_task_definitions(db: Session) -> int:
    """upsert 全域（tenant_id NULL）正式任務定義，回傳處理筆數。"""
    from app.models.mka import TaskDefinition

    count = 0
    for spec in CANONICAL_TASKS:
        row = (
            db.query(TaskDefinition)
            .filter(
                TaskDefinition.tenant_id.is_(None),
                TaskDefinition.task_key == spec["task_key"],
                TaskDefinition.version == "1.0",
            )
            .first()
        )
        if row is None:
            row = TaskDefinition(tenant_id=None, version="1.0")
            db.add(row)
        for key, value in spec.items():
            setattr(row, key, value)
        row.status = "enabled"
        count += 1
    db.flush()
    return count

DEFAULT_JOB_ROLES: List[Dict[str, Any]] = [
    {
        "role_key": "sales",
        "name": "業務",
        "description": "報價、拜訪、請款",
        "default_module_keys": ["sales_quote", "spec_sop"],
    },
    {
        "role_key": "equipment",
        "name": "設備／現場",
        "description": "異常、維修、交接",
        "default_module_keys": ["incident_handover", "spec_sop"],
    },
    {
        "role_key": "quality",
        "name": "品保",
        "description": "客訴、8D、CAPA",
        "default_module_keys": ["quality_8d", "spec_sop"],
    },
    {
        "role_key": "supervisor",
        "name": "主管",
        "description": "審核與跨職能工作台",
        "default_module_keys": [
            "spec_sop", "sales_quote", "incident_handover", "quality_8d", "training_knowhow",
        ],
    },
    {
        "role_key": "newcomer",
        "name": "新人",
        "description": "訓練與必讀",
        "default_module_keys": ["training_knowhow", "spec_sop"],
    },
]


def seed_canonical_modules(db: Session, tenant_id: Optional[UUID] = None) -> int:
    """Upsert 五個正式模組（tenant_id=None 為全租戶定義）。"""
    from app.models.mka import JobModule

    count = 0
    for spec in CANONICAL_MODULES:
        row = (
            db.query(JobModule)
            .filter(
                JobModule.module_key == spec["module_key"],
                JobModule.tenant_id.is_(None) if tenant_id is None else JobModule.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            row = JobModule(tenant_id=tenant_id, module_key=spec["module_key"])
            db.add(row)
            count += 1
        for key, value in spec.items():
            if key in ("module_key", "default_config"):
                # default_config 不是 JobModule 欄位；它是 binding merge 的 base
                continue
            setattr(row, key, value)
        row.status = "enabled"
    db.flush()
    return count


def seed_default_job_roles(db: Session, tenant_id: UUID) -> int:
    from app.models.mka import JobRole

    count = 0
    for spec in DEFAULT_JOB_ROLES:
        row = (
            db.query(JobRole)
            .filter(JobRole.tenant_id == tenant_id, JobRole.role_key == spec["role_key"])
            .first()
        )
        if row is None:
            row = JobRole(tenant_id=tenant_id, role_key=spec["role_key"])
            db.add(row)
            count += 1
        row.name = spec["name"]
        row.description = spec.get("description")
        row.default_module_keys = list(spec.get("default_module_keys") or [])
        row.active = True
    db.flush()
    return count


def ensure_tenant_module_bindings(db: Session, tenant_id: UUID) -> int:
    """為租戶啟用全部正式模組（若尚無 binding）。"""
    from app.models.mka import TenantModuleBinding

    count = 0
    for spec in CANONICAL_MODULES:
        existing = (
            db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.module_key == spec["module_key"],
            )
            .first()
        )
        if existing is None:
            db.add(
                TenantModuleBinding(
                    tenant_id=tenant_id,
                    module_key=spec["module_key"],
                    enabled=True,
                    license_state="active",
                    config_json={},
                )
            )
            count += 1
        elif not existing.enabled:
            existing.enabled = True
    db.flush()
    return count
