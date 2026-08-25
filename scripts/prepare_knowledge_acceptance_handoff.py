#!/usr/bin/env python3
"""Prepare an unsigned, fail-closed handoff bundle for independent KB acceptance.

The bundle freezes the exact backend, frontend, deployment manifest, tenant and
KB revision that external custodians, QA and operators must test.  It never
creates attestations or PASS evidence on their behalf.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SHA256_IMAGE = re.compile(r"sha256:[0-9a-fA-F]{64}")
DEPLOYMENT_ID = re.compile(r"dm-[0-9a-fA-F]{24}")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_binding(deployment_manifest: Path, *, tenant_id: str, revision_id: str, kb_manifest_hash: str) -> dict:
    UUID(tenant_id)
    UUID(revision_id)
    if not re.fullmatch(r"[0-9a-fA-F]{32,64}", kb_manifest_hash):
        raise ValueError("kb-manifest-hash must be 32-64 hexadecimal characters")
    payload = json.loads(deployment_manifest.read_text(encoding="utf-8"))
    deployment_manifest_id = str(payload.get("deployment_manifest_id") or "")
    images = payload.get("candidate_images") or {}
    backend = str((images.get("backend") or {}).get("image_id") or "")
    frontend = str((images.get("frontend") or {}).get("image_id") or "")
    if not DEPLOYMENT_ID.fullmatch(deployment_manifest_id):
        raise ValueError("deployment manifest id is invalid")
    if not SHA256_IMAGE.fullmatch(backend) or not SHA256_IMAGE.fullmatch(frontend):
        raise ValueError("deployment manifest must contain exact backend and frontend image ids")
    return {
        "tenant_id": tenant_id,
        "revision_id": revision_id,
        "kb_manifest_hash": kb_manifest_hash,
        "deployment_manifest_id": deployment_manifest_id,
        "backend_image_digest": backend,
        "frontend_image_digest": frontend,
    }


def _case_rows(names: list[str]) -> list[dict]:
    return [{"name": name, "status": "NOT_RUN", "evidence_refs": []} for name in names]


def prepare_bundle(
    *,
    deployment_manifest: Path,
    output_dir: Path,
    tenant_id: str,
    revision_id: str,
    kb_manifest_hash: str,
) -> Path:
    binding = _load_binding(
        deployment_manifest,
        tenant_id=tenant_id,
        revision_id=revision_id,
        kb_manifest_hash=kb_manifest_hash,
    )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("output directory must be empty; acceptance evidence is never overwritten")
    output_dir.mkdir(parents=True, exist_ok=True)

    runtime_manifest = {
        "image_digest": binding["backend_image_digest"],
        "frontend_image_digest": binding["frontend_image_digest"],
        "deployment_manifest_id": binding["deployment_manifest_id"],
        "model_manifest": {},
        "prompt_hash": "",
        "feature_flags": {},
    }
    personas = {
        "sales": _case_rows(["login", "quote", "customer", "contract", "delivery", "source_expand", "logout_relogin"]),
        "field": _case_rows(["login", "equipment", "work_order", "sop", "incident", "source_expand", "logout_relogin"]),
        "master": _case_rows(["login", "approved_knowhow", "draft_boundary", "sop", "source_expand", "logout_relogin"]),
        "newcomer": _case_rows(["login", "steps", "follow_up", "access_denied", "source_expand", "logout_relogin"]),
        "viewer": _case_rows(["login", "query", "mutation_denied", "approval_denied", "source_expand", "logout_relogin"]),
        "admin": _case_rows(["login", "revision", "permission", "conflict", "approve", "release", "rollback", "logout_relogin"]),
    }
    browser = {
        "runner": {"id": "", "role": "", "independent_of_implementation": False, "attestation_sha256": ""},
        "image_digest": binding["backend_image_digest"],
        "frontend_image_digest": binding["frontend_image_digest"],
        "deployment_manifest_id": binding["deployment_manifest_id"],
        "revision_id": revision_id,
        "manifest_hash": kb_manifest_hash,
        "personas": personas,
        "negative_controls": _case_rows(["deny", "cross_tenant", "cross_department", "kb_membership_conflict"]),
        "pairwise": [],
        "surfaces": _case_rows(["refresh", "back", "empty", "403", "404", "mobile", "source_expand", "multiturn", "numeric_preservation", "admin_release_decision"]),
    }
    operations = {
        "image_digest": binding["backend_image_digest"],
        "revision_id": revision_id,
        "manifest_hash": kb_manifest_hash,
        "operator": {"id": "", "role": "", "attestation_sha256": ""},
        "feedback": {"sampled": 0, "missing_owner": 0, "missing_status": 0, "missing_history": 0},
        "freshness": {"active_documents": 0, "evaluated_documents": 0, "stale_answer_violations": 0, "revoked_answer_violations": 0, "connector_failure_answer_violations": 0},
        "trace_privacy": {"total_traces": 0, "sampled_traces": 0, "sensitive_findings": 0, "unauthorized_raw_content": 0},
        "backup_restore": {"backup_digest": "", "restore_smoke_status": "NOT_RUN", "rollback_status": "NOT_RUN", "rto_seconds": None, "target_rto_seconds": None},
    }
    resources = {
        "image_digest": binding["backend_image_digest"],
        "deployment_profile": "",
        "cpu_peak_percent": None,
        "memory_peak_mb": None,
        "storage_limit_bytes": None,
        "infrastructure_hourly_cost": None,
        "observer": "",
        "attestation_sha256": "",
    }
    files = {
        "binding.json": binding,
        "runtime_manifest.template.json": runtime_manifest,
        "browser_evidence.template.json": browser,
        "operations_evidence.template.json": operations,
        "capacity_resource_observation.template.json": resources,
        "capacity_queries.template.json": [],
        "shadow_queries.template.json": [],
    }
    for name, payload in files.items():
        _write_json(output_dir / name, payload)

    readme = f"""# Enclave 知識庫獨立驗收交接包

狀態：`PREPARED_NOT_ATTESTED`。本目錄只有模板，不代表任何 gate 已通過。

固定候選：

- deployment manifest：`{binding['deployment_manifest_id']}`
- backend：`{binding['backend_image_digest']}`
- frontend：`{binding['frontend_image_digest']}`
- tenant：`{tenant_id}`
- KB revision：`{revision_id}`
- KB manifest：`{kb_manifest_hash}`

執行順序：

1. 獨立 custodian 建立至少 200 案例的 Z5 與兩組不同 sealed holdout；不得使用本模板假造題目或 attestation。
2. Operator 完成 `runtime_manifest.template.json` 的 model、prompt hash 與 flags，在 process-wide read-only 下執行 `run_production_shadow.py`。
3. QA／產品負責人完成 `browser_evidence.template.json` 所有案例、10 組權限 pairwise 與可追查證據。
4. Operator 填寫真實資源觀測與 Ops 演練資料；`NOT_RUN`、空 attestation、空 evidence refs 必定 FAIL。
5. 先執行 `python scripts/verify_knowledge_acceptance_handoff.py --bundle <本目錄>` 驗證交接包未被竄改。
6. 將完成後的證據另存至本目錄之外，再用 `run_external_knowledge_acceptance.py` 執行所有 gate；不可覆寫模板。
7. promotion 會再次核對 backend、frontend、deployment manifest 與 KB revision。

本包不含密碼、token、正式資料本文或自行簽發的 PASS。

完成證據後先執行預檢（PowerShell）：

```powershell
python scripts/run_external_knowledge_acceptance.py `
  --bundle "{output_dir}" `
  --browser-evidence "<completed-evidence>/browser.json" `
  --operations-evidence "<completed-evidence>/operations.json" `
  --runtime-manifest "<completed-evidence>/runtime.json" `
  --shadow-queries "<completed-evidence>/shadow-queries.json" `
  --capacity-queries "<completed-evidence>/capacity-queries.json" `
  --resource-observation "<completed-evidence>/resources.json" `
  --z5-seal "<custodian-evidence>/seal.json" `
  --profile enterprise --preflight-only
```

預檢通過後移除 `--preflight-only`，即會依序執行六個外部 gate 並將結果寫入
`artifacts/knowledge/external_acceptance_run/`。此指令不執行 promotion。
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.iterdir())
        if path.name != "handoff_manifest.json"
    }
    handoff = {
        "schema_version": 1,
        "status": "PREPARED_NOT_ATTESTED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "independent_evidence_present": False,
        "binding": binding,
        "file_sha256": digests,
    }
    manifest_path = output_dir / "handoff_manifest.json"
    _write_json(manifest_path, handoff)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-manifest", type=Path, default=ROOT / "artifacts/knowledge/deployment_manifest.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--kb-manifest-hash", required=True)
    args = parser.parse_args()
    path = prepare_bundle(
        deployment_manifest=args.deployment_manifest,
        output_dir=args.output_dir,
        tenant_id=args.tenant_id,
        revision_id=args.revision_id,
        kb_manifest_hash=args.kb_manifest_hash,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
