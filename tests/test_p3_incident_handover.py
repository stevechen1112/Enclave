"""
MKA P3 — 現場異常/交接測試。
"""
import pytest
from unittest.mock import MagicMock

from app.services.incident_handover import (
    IncidentForm, IncidentSeverity, IncidentStatus,
    SafeGuidancePolicy, get_safe_guidance_policy,
    ShiftHandover, HandoverStatus,
    TaskAssignment, TaskStatus,
    SceneAdapter, get_scene_adapter,
    EMERGENCY_KEYWORDS, DANGER_RESPONSE,
)


class TestSafeGuidancePolicy:
    def test_emergency_detection(self):
        policy = SafeGuidancePolicy()
        assert policy.check_emergency("設備冒煙了") is True
        assert policy.check_emergency("人員受傷") is True
        assert policy.check_emergency("火災") is True

    def test_no_emergency(self):
        policy = SafeGuidancePolicy()
        assert policy.check_emergency("設備正常運轉") is False
        assert policy.check_emergency("查詢 SOP") is False

    def test_high_risk_operation(self):
        policy = SafeGuidancePolicy()
        assert policy.check_high_risk_operation("需要拆卸馬達") is True
        assert policy.check_high_risk_operation("帶電操作") is True

    def test_no_high_risk(self):
        policy = SafeGuidancePolicy()
        assert policy.check_high_risk_operation("查詢規格") is False

    def test_emergency_response(self):
        policy = SafeGuidancePolicy()
        resp = policy.get_safe_response("設備冒煙了")
        assert resp is not None
        assert "緊急" in resp["message"] or "危險" in resp["message"]
        assert len(resp["steps"]) >= 3
        assert "disclaimer" in resp

    def test_high_risk_no_evidence_response(self):
        policy = SafeGuidancePolicy()
        resp = policy.get_safe_response("需要拆卸馬達", has_evidence=False)
        assert resp is not None
        assert "高風險" in resp["message"] or "證據不足" in resp["message"]

    def test_high_risk_with_evidence_no_block(self):
        policy = SafeGuidancePolicy()
        resp = policy.get_safe_response("需要拆卸馬達", has_evidence=True)
        # 有證據時不阻擋（但仍需人工確認）
        assert resp is None

    def test_normal_query_no_block(self):
        policy = SafeGuidancePolicy()
        resp = policy.get_safe_response("查詢 CNC 規格")
        assert resp is None


class TestIncidentForm:
    def test_create_incident(self):
        incident = IncidentForm(
            title="CNC 異常",
            description="主軸震動過大",
            severity=IncidentSeverity.HIGH,
        )
        assert incident.status == IncidentStatus.DRAFT
        assert incident.severity == IncidentSeverity.HIGH

    def test_to_dict(self):
        incident = IncidentForm(
            title="測試",
            description="描述",
            equipment_id="CNC-001",
        )
        d = incident.to_dict()
        assert d["title"] == "測試"
        assert d["equipment_id"] == "CNC-001"
        assert d["status"] == "draft"
        assert d["severity"] == "medium"


class TestShiftHandover:
    def test_create_handover(self):
        h = ShiftHandover(
            shift="早班",
            from_operator="張三",
            to_operator="李四",
        )
        assert h.status == HandoverStatus.DRAFT
        assert h.shift == "早班"

    def test_to_dict(self):
        h = ShiftHandover(
            shift="中班",
            from_operator="A",
            to_operator="B",
            notes="注意設備溫度",
        )
        d = h.to_dict()
        assert d["shift"] == "中班"
        assert d["notes"] == "注意設備溫度"
        assert d["status"] == "draft"


class TestTaskAssignment:
    def test_create_task(self):
        t = TaskAssignment(
            title="維修 CNC-001",
            assigned_to="張三",
            assigned_by="主管",
        )
        assert t.status == TaskStatus.ASSIGNED
        assert t.priority == "medium"

    def test_to_dict(self):
        t = TaskAssignment(title="測試", assigned_to="A")
        d = t.to_dict()
        assert d["title"] == "測試"
        assert d["status"] == "assigned"


class TestSceneAdapter:
    def test_build_retrieval_scope(self):
        scene = MagicMock()
        scene.equipment_id = "CNC-001"
        scene.equipment_model = "VMC-800"
        scene.work_order_id = ""
        scene.product_id = ""
        scene.part_number = "PN-001"

        adapter = SceneAdapter()
        scope = adapter.build_retrieval_scope(scene)
        assert scope["equipment_id"] == "CNC-001"
        assert scope["equipment_model"] == "VMC-800"
        assert scope["part_number"] == "PN-001"
        assert "work_order_id" not in scope  # 空字串不加入

    def test_build_retrieval_scope_empty(self):
        scene = MagicMock()
        scene.equipment_id = ""
        scene.equipment_model = ""
        scene.work_order_id = ""
        scene.product_id = ""
        scene.part_number = ""

        adapter = SceneAdapter()
        scope = adapter.build_retrieval_scope(scene)
        assert scope == {}

    def test_build_incident_from_scene(self):
        scene = MagicMock()
        scene.equipment_id = "CNC-001"
        scene.equipment_model = "VMC-800"
        scene.work_order_id = "WO-001"
        scene.site_id = "S001"
        scene.line_id = "L001"

        adapter = SceneAdapter()
        incident = adapter.build_incident_from_scene(
            scene=scene,
            reporter_id="user-001",
            reporter_name="張三",
            description="主軸異常震動",
        )
        assert incident.equipment_id == "CNC-001"
        assert incident.equipment_model == "VMC-800"
        assert incident.work_order_id == "WO-001"
        assert incident.reporter_name == "張三"
        assert incident.description == "主軸異常震動"
        assert incident.status == IncidentStatus.DRAFT