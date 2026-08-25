import pytest

from app.db.migrations.versions import (
    kb_engine_k1_001,
    mka_p6_task_events_001,
    mka_p7_long_interview_capture_001,
)


class _Inspector:
    def __init__(self, columns_by_table, indexes_by_table=None):
        self.columns_by_table = columns_by_table
        self.indexes_by_table = indexes_by_table or {}

    def get_table_names(self):
        return list(self.columns_by_table)

    def get_columns(self, table):
        return [{"name": name} for name in self.columns_by_table[table]]

    def get_indexes(self, table):
        return [{"name": name} for name in self.indexes_by_table.get(table, ())]


def _fail_create(*_args, **_kwargs):
    raise AssertionError("migration attempted to recreate an adopted table")


def test_p6_adopts_complete_preexisting_event_table(monkeypatch):
    columns = {"mka_task_run_events": {
        "id", "tenant_id", "run_id", "event_type", "actor_id", "payload", "created_at"
    }}
    indexes = {"mka_task_run_events": {
        "ix_mka_task_run_events_tenant_id", "ix_mka_task_run_events_run_id",
        "ix_mka_task_run_events_event_type", "ix_mka_task_run_events_tenant_type",
    }}
    inspector = _Inspector(columns, indexes)
    monkeypatch.setattr(mka_p6_task_events_001.op, "get_bind", lambda: object())
    monkeypatch.setattr(mka_p6_task_events_001.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(mka_p6_task_events_001.op, "create_table", _fail_create)

    mka_p6_task_events_001.upgrade()


def test_p6_rejects_incomplete_preexisting_event_table(monkeypatch):
    inspector = _Inspector({"mka_task_run_events": {"id", "tenant_id"}})
    monkeypatch.setattr(mka_p6_task_events_001.op, "get_bind", lambda: object())
    monkeypatch.setattr(mka_p6_task_events_001.sa, "inspect", lambda _bind: inspector)

    with pytest.raises(RuntimeError, match="missing columns"):
        mka_p6_task_events_001.upgrade()


def test_p7_adopts_complete_preexisting_interview_tables(monkeypatch):
    columns = {
        table: set(required) | {"chunk_id"}
        for table, required in mka_p7_long_interview_capture_001._REQUIRED_COLUMNS.items()
    }
    indexes = {
        table: {name for name, _columns in required}
        for table, required in mka_p7_long_interview_capture_001._REQUIRED_INDEXES.items()
    }
    inspector = _Inspector(columns, indexes)
    monkeypatch.setattr(mka_p7_long_interview_capture_001.op, "get_bind", lambda: object())
    monkeypatch.setattr(mka_p7_long_interview_capture_001.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(mka_p7_long_interview_capture_001.op, "create_table", _fail_create)
    monkeypatch.setattr(mka_p7_long_interview_capture_001.op, "execute", lambda *_args, **_kwargs: None)

    mka_p7_long_interview_capture_001.upgrade()


def test_k1_adopts_complete_preexisting_model_materialization(monkeypatch):
    columns = {
        table: set(required)
        for table, required in kb_engine_k1_001._K1_REQUIRED_COLUMNS.items()
    }
    inspector = _Inspector(columns)
    monkeypatch.setattr(kb_engine_k1_001.op, "get_bind", lambda: object())
    monkeypatch.setattr(kb_engine_k1_001.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(kb_engine_k1_001.op, "create_table", _fail_create)
    for name in (
        "add_column", "create_index", "create_foreign_key", "execute", "alter_column"
    ):
        monkeypatch.setattr(kb_engine_k1_001.op, name, lambda *_args, **_kwargs: None)

    kb_engine_k1_001.upgrade()
