"""
local → S3 物件遷移（CG-STORAGE）

將 ``documents.file_path`` 指向的本機檔案上傳至 S3 相容後端，
並更新 DB 為 ``s3://bucket/<tenant_id>/<doc_id>.<ext>``。

前置：``STORAGE_BACKEND=s3`` 與 S3_* 環境變數已設；DB 可連。

用法：
  python scripts/migrate_storage_local_to_s3.py --dry-run
  python scripts/migrate_storage_local_to_s3.py --execute
  python scripts/migrate_storage_local_to_s3.py --execute --tenant-id <uuid>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT = ROOT / "artifacts" / "storage_migration_last_run.json"


def _local_path_from_uri(file_path: str, upload_dir: str) -> Path | None:
    if not file_path:
        return None
    if file_path.startswith("s3://"):
        return None
    if file_path.startswith("file://"):
        return Path(file_path[7:])
    p = Path(file_path)
    if p.is_file():
        return p
    # 相對 uploads 目錄
    candidate = Path(upload_dir) / file_path
    if candidate.is_file():
        return candidate
    # storage key 形式 tenant/doc.ext
    candidate2 = Path(upload_dir) / file_path.replace("/", os.sep)
    if candidate2.is_file():
        return candidate2
    return None


def migrate(*, execute: bool, tenant_id: str | None) -> int:
    from app.config import settings
    from app.db.session import SessionLocal
    from app.models.document import Document
    from app.services.storage import build_storage_key, get_storage_backend

    if str(settings.STORAGE_BACKEND).lower() != "s3":
        print("ERROR: STORAGE_BACKEND must be 's3' for migration target")
        return 1
    if not settings.S3_BUCKET:
        print("ERROR: S3_BUCKET is required")
        return 1

    backend = get_storage_backend()
    if backend.name != "s3":
        print(f"ERROR: expected s3 backend, got {backend.name}")
        return 1

    db = SessionLocal()
    q = db.query(Document).filter(Document.file_path.isnot(None))
    if tenant_id:
        q = q.filter(Document.tenant_id == UUID(tenant_id))

    docs = q.all()
    stats = {"total": len(docs), "skipped_s3": 0, "missing_file": 0, "migrated": 0, "errors": []}

    for doc in docs:
        fp = doc.file_path or ""
        if fp.startswith("s3://"):
            stats["skipped_s3"] += 1
            continue

        local = _local_path_from_uri(fp, settings.UPLOAD_DIR)
        if not local or not local.is_file():
            stats["missing_file"] += 1
            stats["errors"].append({"document_id": str(doc.id), "reason": "file not found", "file_path": fp})
            continue

        ext = (doc.file_type or local.suffix.lstrip(".") or "bin").lower()
        key = build_storage_key(doc.tenant_id, doc.id, ext)

        if execute:
            try:
                uri = backend.put(key, str(local))
                doc.file_path = uri
                db.add(doc)
                stats["migrated"] += 1
            except Exception as exc:
                stats["errors"].append({"document_id": str(doc.id), "reason": str(exc)})
        else:
            stats["migrated"] += 1
            print(f"  would migrate {doc.id} -> s3://{settings.S3_BUCKET}/{key}")

    if execute and stats["migrated"]:
        db.commit()
    db.close()

    payload = {
        "status": "PASS" if not stats["errors"] else "FAIL",
        "mode": "execute" if execute else "dry-run",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **stats,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not stats["errors"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local uploads to S3")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--execute", action="store_true", help="Perform migration")
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant UUID")
    args = parser.parse_args()
    execute = bool(args.execute)
    if not execute and not args.dry_run:
        args.dry_run = True
    return migrate(execute=execute, tenant_id=args.tenant_id)


if __name__ == "__main__":
    raise SystemExit(main())
