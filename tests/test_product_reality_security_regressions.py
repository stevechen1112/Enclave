from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_post_p2_tenant_policy_reconciliation_covers_every_known_drift() -> None:
    migration = (
        ROOT
        / "app/db/migrations/versions/tenant_policy_reconcile_pra_001.py"
    ).read_text(encoding="utf-8")
    for table in (
        "import_batch_items",
        "import_batches",
        "input_operation_metrics",
        "input_pilot_acceptances",
        "input_pilot_audits",
        "input_pilot_daily_metrics",
        "input_pilot_incidents",
        "input_pilots",
        "knowledge_unit_relation_projections",
        "upload_parts",
        "upload_sessions",
    ):
        assert f'"{table}"' in migration
    assert "pg_has_role(current_user, 'enclave_rls_bypass', 'member')" in migration
    assert 'down_revision: str | None = "knowledge_typed_relation_kq4_001"' in migration


def test_document_reader_handles_shadow_scope_without_revision_key() -> None:
    endpoint = (ROOT / "app/api/v1/endpoints/documents.py").read_text(
        encoding="utf-8"
    )
    assert endpoint.count('scope.get("kb_revision_ids") or []') == 2
    assert 'scope["kb_revision_ids"]' not in endpoint
