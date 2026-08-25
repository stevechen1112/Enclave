"""Single allowlist for the six passwordless demonstration personas."""
from __future__ import annotations

from typing import Any
from uuid import UUID

DEMO_TENANT_ID = UUID("4a8a6ec2-9be7-5d43-a786-2bf4af10f3d1")
DEMO_TENANT_NAME = "Enclave 合成展示工廠（非真實公司）"

DEMO_PERSONAS: dict[str, dict[str, Any]] = {
    "sales": {
        "email": "sales-door@demo.enclave.invalid",
        "full_name": "業務展示 王小明",
        "security_role": "employee",
        "job_role": "sales",
        "department": "業務部",
        "read_only": False,
        "mutation_scope": "workflow",
    },
    "field": {
        "email": "field-door@demo.enclave.invalid",
        "full_name": "現場展示 李阿明",
        "security_role": "employee",
        "job_role": "equipment",
        "department": "設備課",
        "read_only": False,
        "mutation_scope": "workflow",
    },
    "master": {
        "email": "master-door@demo.enclave.invalid",
        "full_name": "師傅展示 林火旺",
        "security_role": "employee",
        "job_role": "master",
        "department": "製造部",
        "read_only": False,
        "mutation_scope": "workflow",
    },
    "newcomer": {
        "email": "newcomer-door@demo.enclave.invalid",
        "full_name": "新人展示 陳小弟",
        "security_role": "employee",
        "job_role": "newcomer",
        "department": "製造部",
        "read_only": False,
        "mutation_scope": "workflow",
    },
    "viewer": {
        "email": "viewer-door@demo.enclave.invalid",
        "full_name": "主管唯讀展示",
        "security_role": "viewer",
        "job_role": None,
        "department": "管理部",
        "read_only": True,
        "mutation_scope": "interaction",
    },
    "admin": {
        "email": "admin-door@demo.enclave.invalid",
        "full_name": "公司管理展示",
        "security_role": "owner",
        "job_role": "supervisor",
        "department": "管理部",
        "read_only": False,
        "mutation_scope": "approval",
    },
}
