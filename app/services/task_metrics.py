"""TaskRun 指標彙總（職能任務平台重構 Phase 7 可觀測性）。

指標定義：
- completion_rate：到達 waiting_review 之後（含）的 run 比例
- error_rate：failed run 比例
- manual_edit_rate：有手動修改欄位的 run 比例（以有欄位來源的 run 為分母）
- field_source_distribution：欄位來源分布（voice/text/knowledge/tool/rule/user/default）
- approval_cycle_hours_avg：表單簽核平均耗時（已決議的 approval request）
"""
from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.workflow import MKAApprovalRequest, TaskRun, TaskRunEvent

_DONE_STATUSES = {"waiting_review", "approved", "rejected", "executed", "exported"}


def compute_task_metrics(db: Session, tenant_id: UUID) -> Dict[str, Any]:
    runs = db.query(TaskRun).filter(TaskRun.tenant_id == tenant_id).all()
    total = len(runs)
    by_status: Dict[str, int] = {}
    for r in runs:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    done = sum(by_status.get(s, 0) for s in _DONE_STATUSES)
    failed = by_status.get("failed", 0)

    # 欄位來源分布 + 手動修改率
    source_dist: Dict[str, int] = {}
    runs_with_sources = 0
    runs_with_manual_edits = 0
    for r in runs:
        sources = r.field_sources or {}
        if sources:
            runs_with_sources += 1
            for meta in sources.values():
                if isinstance(meta, dict):
                    src = meta.get("source", "unknown")
                    source_dist[src] = source_dist.get(src, 0) + 1
        edits = (r.provenance or {}).get("manual_edits") or []
        if edits:
            runs_with_manual_edits += 1

    # 簽核效率：已決議的表單簽核平均耗時（小時）
    approvals = (
        db.query(MKAApprovalRequest)
        .filter(
            MKAApprovalRequest.tenant_id == tenant_id,
            MKAApprovalRequest.status.in_(["approved", "rejected"]),
        )
        .all()
    )
    cycle_hours = []
    for a in approvals:
        if a.created_at and a.updated_at:
            delta = a.updated_at - a.created_at
            cycle_hours.append(delta.total_seconds() / 3600.0)
    avg_cycle = round(sum(cycle_hours) / len(cycle_hours), 2) if cycle_hours else None

    # 事件量（除錯與行為分析用）
    event_count = (
        db.query(TaskRunEvent)
        .filter(TaskRunEvent.tenant_id == tenant_id)
        .count()
    )

    return {
        "total_runs": total,
        "by_status": by_status,
        "completion_rate": round(done / total, 4) if total else None,
        "error_rate": round(failed / total, 4) if total else None,
        "manual_edit_rate": (
            round(runs_with_manual_edits / runs_with_sources, 4)
            if runs_with_sources else None
        ),
        "field_source_distribution": source_dist,
        "approval_decided_count": len(approvals),
        "approval_cycle_hours_avg": avg_cycle,
        "event_count": event_count,
        "computed_at": datetime.now().isoformat(),
    }
