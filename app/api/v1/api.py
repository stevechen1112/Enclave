from fastapi import APIRouter
from app.api.v1.endpoints import (
    admin,
    agent,
    analytics,
    audit,
    auth,
    chat,
    chat_analytics,
    company,
    departments,
    documents,
    experience,
    feature_flags,
    forms,
    gateway,
    connectors,
    wiki,
    operations,
    agent_approvals,
    graph,
    generate,
    kb,
    kb_maintenance,
    mcp,
    mobile,
    payment,
    reports,
    sso,
    tenants,
    users,
    voice,
    internal_service_auth,
    knowhow,
    mka_approvals,
    interaction,
    scene,
    scene_admin,
    job_modules,
    job_roles,
    tasks,
    terms,
    audio_policy,
    form_templates,
    enterprise,
    mka_metrics,
    interview,
    knowledge_capture,
    realtime_voice,
    knowledge_control,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(sso.router, prefix="/sso", tags=["sso"])
api_router.include_router(experience.router, prefix="/experience", tags=["experience"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(kb.router, prefix="/kb", tags=["knowledge-base"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(chat_analytics.router, prefix="/chat", tags=["analytics"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(departments.router, prefix="/departments", tags=["departments"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(feature_flags.router, prefix="/feature-flags", tags=["feature-flags"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
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
api_router.include_router(payment.router, prefix="/payment", tags=["payment"])
# Phase 1 — Knowledge Gateway（統一知識庫搜尋）
api_router.include_router(gateway.router, tags=["gateway"])
api_router.include_router(connectors.router, tags=["connectors"])
api_router.include_router(wiki.router, tags=["wiki"])
api_router.include_router(operations.router, tags=["operations"])
api_router.include_router(agent_approvals.router, tags=["agent-approvals"])
api_router.include_router(mka_approvals.router, tags=["mka-approvals"])
api_router.include_router(knowhow.router, tags=["knowhow"])
api_router.include_router(graph.router, tags=["graph"])
api_router.include_router(internal_service_auth.router, tags=["internal-service-auth"])
# P3-2 — Read-only FastMCP Server
api_router.include_router(mcp.router, tags=["mcp"])
# P1-1 — Voice STT/TTS
api_router.include_router(voice.router, tags=["voice"])
# P1-2 — Fixed Form
api_router.include_router(forms.router, tags=["forms"])
# MKA-P1 — Interaction API (§5.2)
api_router.include_router(interaction.router, tags=["interaction"])
# MKA-P1 — Scene API (§5.3)
api_router.include_router(scene.router, tags=["scene"])
api_router.include_router(scene_admin.router, tags=["scene-admin"])
# MKA-P4 — Module Admin API (§5.4)
api_router.include_router(job_modules.router, tags=["job-modules"])
api_router.include_router(job_roles.router, tags=["job-roles"])
api_router.include_router(tasks.router, tags=["tasks"])
# MKA-P1 — Term Dictionary API (§4.5)
api_router.include_router(terms.router, tags=["terms"])
# MKA — Audio Retention Policy API (§12.1)
api_router.include_router(audio_policy.router, tags=["audio-policy"])
# MKA — 公司版型／企業整合／指標／訪談
api_router.include_router(form_templates.router, tags=["form-templates"])
api_router.include_router(enterprise.router, tags=["enterprise"])
api_router.include_router(mka_metrics.router, tags=["mka-metrics"])
api_router.include_router(interview.router, tags=["interview"])
api_router.include_router(knowledge_capture.router, tags=["knowledge-captures"])
api_router.include_router(realtime_voice.router, tags=["voice-realtime"])
api_router.include_router(knowledge_control.router, tags=["knowledge-control"])
