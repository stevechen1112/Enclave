"""Sidecar 租戶綁定解析服務（ADR-013）。

紀律：
- ``get_binding`` 找不到 binding 一律 raise（fail-closed），不得 fallback 到
  全域環境變數——環境變數僅供 migration 種子與 adapter 層部署級預設。
- pack 未啟用（對應欄位 NULL）回傳 None，由呼叫端決定跳過該 sidecar 臂；
  這與「binding 不存在」是不同的語意（前者是設定狀態，後者是隔離破口）。
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.sidecar_binding import TenantSidecarBinding

logger = logging.getLogger(__name__)


class SidecarBindingError(RuntimeError):
    """租戶無 sidecar binding——隔離邊界缺失，fail-closed。"""


def get_binding(db: Session, tenant_id: UUID) -> TenantSidecarBinding:
    """取租戶的 sidecar binding；不存在即 raise（不得靜默落到全域預設）。"""
    binding = (
        db.query(TenantSidecarBinding)
        .filter(TenantSidecarBinding.tenant_id == tenant_id)
        .first()
    )
    if binding is None:
        raise SidecarBindingError(
            f"no sidecar binding for tenant {tenant_id} — "
            "tenant provisioning must create one (ADR-013)"
        )
    return binding


def ensure_binding(db: Session, tenant_id: UUID) -> TenantSidecarBinding:
    """租戶建立時呼叫：建立空 binding（各 pack NULL＝未啟用）。冪等。"""
    existing = (
        db.query(TenantSidecarBinding)
        .filter(TenantSidecarBinding.tenant_id == tenant_id)
        .first()
    )
    if existing is not None:
        return existing
    binding = TenantSidecarBinding(tenant_id=tenant_id)
    db.add(binding)
    db.flush()
    return binding


def resolve_ragflow_dataset_id(db: Session, tenant_id: UUID) -> Optional[str]:
    """租戶的 RAGFlow dataset；binding 缺失 raise，pack 未啟用回 None。"""
    return get_binding(db, tenant_id).ragflow_dataset_id or None


def resolve_weknora_kb_id(db: Session, tenant_id: UUID) -> Optional[str]:
    """租戶的 WeKnora KB；binding 缺失 raise，pack 未啟用回 None。"""
    return get_binding(db, tenant_id).weknora_kb_id or None


def legacy_env_dataset_id() -> Optional[str]:
    """部署級預設（僅限無租戶上下文的維運腳本／測試；控制面路徑禁用）。"""
    return (os.getenv("RAGFLOW_DATASET_ID") or "").strip() or None


def legacy_env_kb_id() -> Optional[str]:
    """部署級預設（同上限制）。"""
    return (
        (os.getenv("WEKNORA_KB_ID") or "").strip()
        or (os.getenv("WEKNORA_DEFAULT_KB_ID") or "").strip()
        or None
    )
