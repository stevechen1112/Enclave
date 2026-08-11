"""
MKA-P3：現場異常/交接 — incident form + scene adapter + handover state。

對照 ENGINEERING_PLAN.md §8 MKA-P3：
- equipment/work-order scene adapter
- incident form schema
- attachment metadata
- safe guidance policy
- task assignment
- shift handover state
- notification outbox

安全邊界（§MKA-P3 安全邊界）：
- 不宣稱故障診斷取代維修人員
- 緊急/危險關鍵字優先顯示停機與聯絡程序
- 不在證據不足時提供高風險操作步驟
- 照片分析初期只作附件與人工檢視
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


# ── Incident Form ──

class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    DRAFT = "draft"
    REPORTED = "reported"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"


@dataclass
class IncidentForm:
    """異常報告表單。"""
    incident_id: str = ""
    title: str = ""
    description: str = ""
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    status: IncidentStatus = IncidentStatus.DRAFT
    # 場景
    equipment_id: str = ""
    equipment_model: str = ""
    work_order_id: str = ""
    site_id: str = ""
    line_id: str = ""
    # 人員
    reporter_id: str = ""
    reporter_name: str = ""
    assigned_to: str = ""
    # 內容
    symptoms: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    root_cause: str = ""
    resolution: str = ""
    # 附件
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    # 安全
    safety_warnings: List[str] = field(default_factory=list)
    requires_shutdown: bool = False
    # SOP 引用
    related_sop_ids: List[str] = field(default_factory=list)
    # 時間
    occurred_at: str = ""
    reported_at: str = ""
    resolved_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "status": self.status.value,
            "equipment_id": self.equipment_id,
            "equipment_model": self.equipment_model,
            "work_order_id": self.work_order_id,
            "site_id": self.site_id,
            "line_id": self.line_id,
            "reporter_id": self.reporter_id,
            "reporter_name": self.reporter_name,
            "assigned_to": self.assigned_to,
            "symptoms": self.symptoms,
            "actions_taken": self.actions_taken,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "attachments": self.attachments,
            "safety_warnings": self.safety_warnings,
            "requires_shutdown": self.requires_shutdown,
            "related_sop_ids": self.related_sop_ids,
            "occurred_at": self.occurred_at,
            "reported_at": self.reported_at,
            "resolved_at": self.resolved_at,
        }


# ── Safe Guidance Policy ──

# 緊急/危險關鍵字 — 優先顯示停機與聯絡程序
EMERGENCY_KEYWORDS = [
    "火災", "爆炸", "漏電", "觸電", "倒塌", "崩塌",
    "有毒", "毒氣", "洩漏", "化學", "輻射",
    "人員受傷", "人員昏迷", "急救", "休克",
    "冒煙", "異味", "火花",
]

# 高風險操作關鍵字 — 不在證據不足時提供
HIGH_RISK_OPERATION_KEYWORDS = [
    "拆卸", "拆解", "強制", "bypass", "旁路", "跳過安全",
    "帶電操作", "高壓", "高溫", "化學清洗",
]

DANGER_RESPONSE = {
    "message": "偵測到可能的緊急/危險情況。請立即：",
    "steps": [
        "1. 確保人員安全，必要時立即撤離",
        "2. 依緊急應變程序停機",
        "3. 聯絡安全主管/廠務",
        "4. 在安全無虞前不進行任何操作",
    ],
    "disclaimer": "本系統不取代合格維修/安全人員判斷。",
}


class SafeGuidancePolicy:
    """安全指引政策（§MKA-P3 安全邊界）。"""

    def check_emergency(self, text: str) -> bool:
        """檢查是否含緊急/危險關鍵字。"""
        text_lower = text.lower()
        return any(kw in text or kw.lower() in text_lower for kw in EMERGENCY_KEYWORDS)

    def check_high_risk_operation(self, text: str) -> bool:
        """檢查是否含高風險操作關鍵字。"""
        text_lower = text.lower()
        return any(kw in text or kw.lower() in text_lower for kw in HIGH_RISK_OPERATION_KEYWORDS)

    def get_safe_response(self, text: str, has_evidence: bool = False) -> Optional[Dict[str, Any]]:
        """根據安全政策決定回應。

        Returns:
            None = 安全可繼續；dict = 需要安全介入
        """
        if self.check_emergency(text):
            return DANGER_RESPONSE

        if self.check_high_risk_operation(text) and not has_evidence:
            return {
                "message": "此操作涉及高風險，系統在證據不足時不提供操作步驟。",
                "steps": [
                    "1. 請查閱正式 SOP 或設備手冊",
                    "2. 聯絡合格維修人員",
                    "3. 確認安全措施後再執行",
                ],
                "disclaimer": "本系統不取代合格維修/安全人員判斷。",
            }

        return None


# ── Shift Handover State ──

class HandoverStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"


@dataclass
class ShiftHandover:
    """交接紀錄。"""
    handover_id: str = ""
    shift: str = ""  # 早班 | 中班 | 晚班
    from_operator: str = ""
    to_operator: str = ""
    status: HandoverStatus = HandoverStatus.DRAFT
    # 交接內容
    ongoing_tasks: List[Dict[str, Any]] = field(default_factory=list)
    completed_tasks: List[Dict[str, Any]] = field(default_factory=list)
    pending_incidents: List[str] = field(default_factory=list)  # incident IDs
    equipment_status: Dict[str, str] = field(default_factory=dict)  # equipment_id → status
    notes: str = ""
    # 時間
    shift_start: str = ""
    shift_end: str = ""
    submitted_at: str = ""
    acknowledged_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handover_id": self.handover_id,
            "shift": self.shift,
            "from_operator": self.from_operator,
            "to_operator": self.to_operator,
            "status": self.status.value,
            "ongoing_tasks": self.ongoing_tasks,
            "completed_tasks": self.completed_tasks,
            "pending_incidents": self.pending_incidents,
            "equipment_status": self.equipment_status,
            "notes": self.notes,
            "shift_start": self.shift_start,
            "shift_end": self.shift_end,
            "submitted_at": self.submitted_at,
            "acknowledged_at": self.acknowledged_at,
        }


# ── Task Assignment ──

class TaskStatus(str, Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass
class TaskAssignment:
    """待辦任務指派。"""
    task_id: str = ""
    title: str = ""
    description: str = ""
    assigned_to: str = ""
    assigned_by: str = ""
    status: TaskStatus = TaskStatus.ASSIGNED
    priority: str = "medium"  # low | medium | high | urgent
    due_at: str = ""
    related_incident_id: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "status": self.status.value,
            "priority": self.priority,
            "due_at": self.due_at,
            "related_incident_id": self.related_incident_id,
            "created_at": self.created_at,
        }


# ── Scene Adapter ──

class SceneAdapter:
    """設備/工單場景適配器 — 從 SceneContext 產生檢索範圍。"""

    def build_retrieval_scope(
        self,
        scene: Any,  # SceneContext
    ) -> Dict[str, Any]:
        """從場景產生檢索 filter。"""
        scope: Dict[str, Any] = {}
        if scene.equipment_id:
            scope["equipment_id"] = scene.equipment_id
        if scene.equipment_model:
            scope["equipment_model"] = scene.equipment_model
        if scene.work_order_id:
            scope["work_order_id"] = scene.work_order_id
        if scene.product_id:
            scope["product_id"] = scene.product_id
        if scene.part_number:
            scope["part_number"] = scene.part_number
        return scope

    def build_incident_from_scene(
        self,
        scene: Any,
        reporter_id: str,
        reporter_name: str,
        description: str,
    ) -> IncidentForm:
        """從場景 + 描述建立異常報告草稿。"""
        return IncidentForm(
            incident_id=str(uuid4()),
            description=description,
            reporter_id=reporter_id,
            reporter_name=reporter_name,
            equipment_id=scene.equipment_id,
            equipment_model=scene.equipment_model,
            work_order_id=scene.work_order_id,
            site_id=scene.site_id,
            line_id=scene.line_id,
            status=IncidentStatus.DRAFT,
        )


# ── 單例 ──

_safe_policy: Optional[SafeGuidancePolicy] = None
_scene_adapter: Optional[SceneAdapter] = None


def get_safe_guidance_policy() -> SafeGuidancePolicy:
    global _safe_policy
    if _safe_policy is None:
        _safe_policy = SafeGuidancePolicy()
    return _safe_policy


def get_scene_adapter() -> SceneAdapter:
    global _scene_adapter
    if _scene_adapter is None:
        _scene_adapter = SceneAdapter()
    return _scene_adapter