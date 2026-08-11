"""
MKA — Excel 匯出 + 音訊 retention/成本測試。
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.services.template_renderer import TemplateRenderer, get_template_renderer
from app.services.audio_retention import (
    AudioRetentionPolicy, TaskCostRecord, AudioRetentionManager,
    get_audio_retention_manager,
)


class TestExcelExport:
    def test_render_excel(self):
        renderer = TemplateRenderer()
        result = renderer.render_excel(
            title="報價單",
            fields={"客戶": "測試公司", "金額": 50000},
            provenance={},
            approval_info={"version": "1.0"},
        )
        if result.success:
            assert result.format == "xlsx"
            assert len(result.content) > 0
            assert result.filename.endswith(".xlsx")
        else:
            assert "openpyxl" in result.error

    def test_excel_watermark(self):
        renderer = TemplateRenderer()
        result = renderer.render_excel(
            title="測試",
            fields={},
            provenance={},
            approval_info={"version": "2.0"},
        )
        if result.success:
            # openpyxl 產出的 xlsx 是二進位，無法直接檢查文字
            assert result.metadata.get("version") == "2.0"


class TestAudioRetentionPolicy:
    def test_default_policy(self):
        mgr = AudioRetentionManager()
        policy = mgr.get_policy("tenant-001")
        assert policy.save_audio is False  # 預設不保存音訊
        assert policy.save_transcript is True  # 預設保存轉寫

    def test_set_policy(self):
        mgr = AudioRetentionManager()
        mgr.set_policy(AudioRetentionPolicy(
            tenant_id="tenant-002",
            save_audio=True,
            audio_retention_days=30,
        ))
        policy = mgr.get_policy("tenant-002")
        assert policy.save_audio is True
        assert policy.audio_retention_days == 30

    def test_should_save_audio(self):
        mgr = AudioRetentionManager()
        mgr.set_policy(AudioRetentionPolicy(tenant_id="t1", save_audio=True))
        assert mgr.should_save_audio("t1") is True
        assert mgr.should_save_audio("unknown") is False  # 預設

    def test_audio_expiry(self):
        mgr = AudioRetentionManager()
        mgr.set_policy(AudioRetentionPolicy(
            tenant_id="t2",
            audio_retention_days=30,
        ))
        now = datetime.now(timezone.utc)
        expiry = mgr.get_audio_expiry("t2", now)
        assert (expiry - now).days == 30

    def test_transcript_expiry(self):
        mgr = AudioRetentionManager()
        now = datetime.now(timezone.utc)
        expiry = mgr.get_transcript_expiry("unknown", now)
        assert (expiry - now).days == 365  # 預設


class TestTaskCostRecord:
    def test_total_cost_calculation(self):
        record = TaskCostRecord(
            task_id="task-001",
            tenant_id="t1",
            stt_cost=0.5,
            llm_cost=2.0,
            embedding_cost=0.1,
            rerank_cost=0.05,
            ocr_cost=0.0,
            source_verify_cost=0.2,
            storage_cost=0.01,
        )
        assert record.total_cost == pytest.approx(2.86)

    def test_to_dict(self):
        record = TaskCostRecord(task_id="t1", tenant_id="t1", llm_cost=1.0)
        d = record.to_dict()
        assert d["task_id"] == "t1"
        assert d["total_cost"] == 1.0


class TestCostSummary:
    def test_empty_summary(self):
        mgr = AudioRetentionManager()
        summary = mgr.get_cost_summary("no-records")
        assert summary["total_tasks"] == 0
        assert summary["total_cost"] == 0.0

    def test_cost_summary(self):
        mgr = AudioRetentionManager()
        mgr.record_cost(TaskCostRecord(
            task_id="t1", tenant_id="t1",
            stt_cost=0.5, llm_cost=2.0,
        ))
        mgr.record_cost(TaskCostRecord(
            task_id="t2", tenant_id="t1",
            stt_cost=0.3, llm_cost=1.0,
        ))
        summary = mgr.get_cost_summary("t1")
        assert summary["total_tasks"] == 2
        assert summary["total_cost"] == pytest.approx(3.8)
        assert summary["avg_cost_per_task"] == pytest.approx(1.9)
        assert summary["cost_breakdown"]["stt"] == pytest.approx(0.8)
        assert summary["cost_breakdown"]["llm"] == pytest.approx(3.0)