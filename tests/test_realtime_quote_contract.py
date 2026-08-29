from types import SimpleNamespace

import pytest


def test_quote_realtime_tools_never_expose_submit_or_export():
    from app.packs.sales_quote.endpoints.realtime_voice import _instructions, _tool_parameters

    parameters = _tool_parameters()
    assert parameters["additionalProperties"] is False
    assert "subtotal" not in parameters["properties"]
    assert "total" not in parameters["properties"]
    prompt = _instructions(
        SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            status="draft",
            input_snapshot={"values": {}},
        )
    )
    assert "不是替使用者核准、送審或匯出" in prompt
    assert "絕對不要聲稱已完成送審" in prompt


def test_quote_state_calculates_totals_and_requires_user_review():
    from app.packs.sales_quote.endpoints.realtime_voice import _quote_state

    run = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        status="draft",
        input_snapshot={
            "values": {
                "customer": "測試客戶",
                "part_number": "P-100",
                "quantity": 2,
                "unit_price": 100,
                "tax_rate": 5,
                "valid_until": "2026-09-30",
                "payment_terms": "月結30天",
            }
        },
    )
    state = _quote_state(run)
    assert state["missing_fields"] == []
    assert state["ready_for_user_review"] is True
    assert state["values"]["subtotal"] == 200
    assert state["values"]["tax"] == 10
    assert state["values"]["total"] == 210
    assert "親自" in state["next_action"]


def test_quote_tool_value_validation_rejects_bad_dates_and_ranges():
    from app.packs.sales_quote.endpoints.realtime_voice import _coerce_quote_value, _quote_schema

    fields = {field.name: field for field in _quote_schema().fields}
    with pytest.raises(ValueError):
        _coerce_quote_value(fields["quantity"], 0)
    with pytest.raises(ValueError):
        _coerce_quote_value(fields["valid_until"], "tomorrow")
    with pytest.raises(ValueError):
        _coerce_quote_value(fields["unit_price"], "NaN")
    with pytest.raises(ValueError):
        _coerce_quote_value(fields["unit_price"], "Infinity")


def test_long_interview_migration_enables_tenant_rls():
    from pathlib import Path

    migration = Path("app/db/migrations/versions/mka_p7_long_interview_capture_001.py").read_text(encoding="utf-8")
    for table in (
        "mka_knowledge_capture_sessions",
        "mka_knowledge_capture_chunks",
        "mka_knowledge_capture_transcript_segments",
    ):
        assert table in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY tenant_isolation" in migration
