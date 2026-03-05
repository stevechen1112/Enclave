from fastapi import APIRouter
from app.api.v1.endpoints import (
    admin,
    agent,
    audit,
    auth,
    chat,
    chat_analytics,
    company,
    departments,
    documents,
    feature_flags,
    generate,
    kb,
    kb_maintenance,
    mobile,
    reports,
    tenants,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(kb.router, prefix="/kb", tags=["knowledge-base"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(chat_analytics.router, prefix="/chat", tags=["analytics"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(departments.router, prefix="/departments", tags=["departments"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(feature_flags.router, prefix="/feature-flags", tags=["feature-flags"])
# analytics.router removed — 前端未使用，進階分析功能暫時停用
api_router.include_router(tenants.router, prefix="/organization", tags=["organization"])
# Phase 10 — 主動索引 Agent
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
# Phase 11 — 內容生成
api_router.include_router(generate.router, prefix="/generate", tags=["generate"])
# Phase 11-2 — 報告管理（共用 /generate 前綴）
api_router.include_router(reports.router, prefix="/generate", tags=["reports"])
# Phase 12 — 行動端 App 後端 endpoints（refresh-token, push-token, security events, cert-fingerprint）
api_router.include_router(mobile.router, prefix="/mobile", tags=["mobile"])
# Phase 13 — 知識庫主動維護（版本管理 / 健康度 / 缺口偵測 / 備份 / 分類 / 使用統計）
api_router.include_router(kb_maintenance.router, prefix="/kb-maintenance", tags=["kb-maintenance"])
# T3-2 — 公司自助管理（Owner/Admin 使用）
api_router.include_router(company.router, prefix="/company", tags=["company"])
