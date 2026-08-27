from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.migrations.versions import (
    asset_identity_b1_007,
    ingestion_job_c1_008,
    knowledge_authority_h1_012,
    multimodal_timeline_f2_010,
    video_artifact_review_f1_009,
    video_governance_f3_011,
)
from app.services.rollback_gate import (
    PROTECTED_OBJECT_KINDS,
    evaluate_rollback_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def _render_downgrade(module) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.downgrade()
    return output.getvalue()


def test_every_modular_migration_renders_a_downgrade_plan():
    modules = (
        asset_identity_b1_007,
        ingestion_job_c1_008,
        video_artifact_review_f1_009,
        multimodal_timeline_f2_010,
        video_governance_f3_011,
        knowledge_authority_h1_012,
    )
    for module in modules:
        sql = _render_downgrade(module)
        assert sql.strip(), module.__name__
        assert "DROP" in sql.upper() or "ALTER" in sql.upper()


def test_blank_operator_template_fails_closed():
    evidence = json.loads(
        (ROOT / "docs" / "templates" / "MODULAR_ROLLBACK_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    result = evaluate_rollback_evidence(evidence)
    assert result["status"] == "HOLD"
    assert result["errors"]


def test_complete_operator_evidence_contract_passes():
    evidence = {
        "deployment": {
            "manifest_id": "dm-test",
            "backend_image": "sha256:b",
            "frontend_image": "sha256:f",
            "worker_image": "sha256:w",
        },
        "backup_restore": {
            "database_backup_sha256": "a" * 64,
            "object_backup_sha256": "b" * 64,
            "restore_status": "PASS",
            "isolated_environment": True,
            "restore_rto_seconds": 120,
        },
        "database_downgrade": {
            "status": "PASS",
            "from_revision": "head",
            "to_revision": "n-1",
            "new_kind_compatibility_scan": "PASS",
        },
        "object_store": {
            "inventory_status": "PASS",
            "protected_kinds": sorted(PROTECTED_OBJECT_KINDS),
            "deleted_during_drill": 0,
        },
        "rollback_smoke": {
            "asset_read": "PASS",
            "review": "PASS",
            "sealed_retrieval": "PASS",
            "tenant_isolation": "PASS",
        },
        "operator": "release-operator@example.invalid",
        "completed_at": "2026-08-27T00:00:00Z",
    }
    assert evaluate_rollback_evidence(evidence) == {"status": "PASS", "errors": []}
