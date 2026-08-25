"""
完整垂直切片 E2E（Pilot 閘門）：
  NAS local connector → materialize → RAGFlow parse → index → search hits
  → tombstone/revoke → search miss + get 404

用法（API + Celery 需運行；RAGFlow 必須可用）：
  set RAGFLOW_ENABLED=true
  set RAGFLOW_FORCE_PARSE=true
  python scripts/e2e_vertical_slice_full.py

通過條件：寫入 artifacts/pilot_e2e_last_run.json 且 status=PASS
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ["PIPESHUB_ALLOW_MOCK"] = "false"
# Pilot：強制 RAGFlow；不可用則 FAIL
os.environ["RAGFLOW_FORCE_PARSE"] = "true"
os.environ.setdefault("RAGFLOW_ENABLED", "true")

BASE = os.getenv("E2E_API_BASE", "http://localhost:8000/api/v1")
EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ["E2E_ADMIN_PASSWORD"]

NAS_DIR = ROOT / "tests" / "fixtures" / "nas_share"
SAMPLE = NAS_DIR / "quality_manual.pdf"
QUERY = "品質管理"
ARTIFACT = ROOT / "artifacts" / "pilot_e2e_last_run.json"


def _write_artifact(payload: dict) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _login(client: httpx.Client) -> dict:
    r = client.post(
        "/auth/login/access-token",
        data={"username": EMAIL, "password": PASSWORD},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _wait_docs(client: httpx.Client, headers: dict, doc_ids: list[str], timeout_s: int = 180) -> dict:
    deadline = time.time() + timeout_s
    statuses: dict[str, str] = {}
    pending = set(doc_ids)
    while pending and time.time() < deadline:
        done = set()
        for did in list(pending):
            d = client.get(f"/documents/{did}", headers=headers)
            if d.status_code != 200:
                continue
            body = d.json()
            st = body.get("status")
            statuses[did] = st
            print(f"  doc {did[:8]} status={st} engine={body.get('parse_engine') or body.get('metadata', {})}")
            if st in ("completed", "failed"):
                done.add(did)
        pending -= done
        if pending:
            time.sleep(3)
    return statuses


def _make_sample_pdf() -> None:
    NAS_DIR.mkdir(parents=True, exist_ok=True)
    # Minimal PDF with Chinese text via reportlab if available; else write a simple PDF stream
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        c = canvas.Canvas(str(SAMPLE))
        c.drawString(72, 720, "Manufacturing Quality Manual")
        c.drawString(72, 700, "ISO 9001 quality management process")
        c.drawString(72, 680, "Incoming inspection and process control")
        c.save()
        return
    except Exception:
        pass
    # Minimal valid PDF bytes
    content = b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 88 >>stream
BT /F1 12 Tf 72 720 Td (Manufacturing Quality Manual ISO 9001) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000405 00000 n 
trailer<< /Size 6 /Root 1 0 R >>
startxref
482
%%EOF
"""
    SAMPLE.write_bytes(content)


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    print("=== Pilot Vertical Slice: NAS → RAGFlow → search → revoke → deny ===\n")

    result = {
        "started_at": started,
        "status": "FAIL",
        "mode": None,
        "document_ids": [],
        "parse_engine": None,
        "search_hit_before": False,
        "get_after_revoke": None,
        "search_leak_after": None,
        "error": None,
    }

    try:
        # Preflight RAGFlow
        ragflow_url = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380")
        try:
            hz = httpx.get(f"{ragflow_url}/api/v1/system/healthz", timeout=10.0)
            if hz.status_code != 200:
                raise RuntimeError(f"RAGFlow health HTTP {hz.status_code}")
            print(f"RAGFlow health: OK ({ragflow_url})")
        except Exception as exc:
            result["error"] = f"ragflow_unavailable:{exc}"
            _write_artifact(result)
            print(f"FAIL: RAGFlow required for Pilot — {exc}")
            return 1

        _make_sample_pdf()
        client = httpx.Client(base_url=BASE, timeout=180.0)
        try:
            h = client.get("/health")
            print(f"API health: {h.status_code}")
            if h.status_code != 200:
                # try alternate
                h = client.get("../health")
        except Exception as exc:
            result["error"] = f"api_unreachable:{exc}"
            _write_artifact(result)
            print(f"API unreachable: {exc}")
            return 1

        # health may be at /health not under /api/v1
        headers = _login(client)
        print(f"Login OK: {EMAIL}")

        body = {
            "connector_type": "nas_smb",
            "name": f"NAS Pilot {uuid.uuid4().hex[:6]}",
            "config": {
                "root_path": str(NAS_DIR.resolve()),
                "principal_external_id": "nas-local-reader",
                "max_files": 20,
            },
        }
        created = client.post("/connectors/", json=body, headers=headers)
        print(f"create connector: {created.status_code}")
        if created.status_code not in (200, 201):
            result["error"] = created.text[:300]
            _write_artifact(result)
            return 1
        connector_id = created.json()["id"]

        synced = client.post(f"/connectors/{connector_id}/sync", headers=headers)
        print(f"sync: {synced.status_code}")
        if synced.status_code != 200:
            result["error"] = synced.text[:300]
            _write_artifact(result)
            return 1
        sync_body = synced.json()
        result["mode"] = sync_body.get("mode")
        if sync_body.get("status") != "completed":
            result["error"] = f"sync_status:{sync_body}"
            _write_artifact(result)
            return 1
        if sync_body.get("mode") == "local_mock":
            result["error"] = "used_mock_mode"
            _write_artifact(result)
            print("FAIL: used mock mode")
            return 1

        doc_ids = sync_body.get("document_ids") or []
        result["document_ids"] = doc_ids
        print(f"mode={sync_body.get('mode')} documents={doc_ids}")
        if not doc_ids:
            result["error"] = "no_document_ids"
            _write_artifact(result)
            return 1

        statuses = _wait_docs(client, headers, doc_ids)
        for did in doc_ids:
            if statuses.get(did) != "completed":
                # Force process for Windows without celery
                from app.tasks.document_tasks import process_document_task
                from app.db.session import SessionLocal
                from app.models.document import Document
                db = SessionLocal()
                try:
                    doc = db.query(Document).filter(Document.id == uuid.UUID(did)).first()
                    if doc and doc.file_path:
                        process_document_task.run(
                            document_id=did,
                            file_path=doc.file_path,
                            tenant_id=str(doc.tenant_id),
                        )
                finally:
                    db.close()
        statuses = _wait_docs(client, headers, doc_ids, timeout_s=120)

        # Verify parse engine is RAGFlow when forced
        d0 = client.get(f"/documents/{doc_ids[0]}", headers=headers)
        doc_json = d0.json() if d0.status_code == 200 else {}
        parse_engine = str(doc_json.get("parse_engine") or "")
        meta = doc_json.get("metadata") or {}
        quality = doc_json.get("quality_report") or {}
        if isinstance(meta, dict):
            parse_engine = parse_engine or str(meta.get("parse_engine") or "")
        if isinstance(quality, dict):
            parse_engine = parse_engine or str(quality.get("parse_engine") or "")
        result["parse_engine"] = parse_engine
        if statuses.get(doc_ids[0]) == "failed":
            result["error"] = f"parse_failed:{doc_json.get('error_message')}"
            _write_artifact(result)
            return 1
        # Pilot 要求真實 RAGFlow 解析路徑，不得以文件 status 冒充 engine
        engine_l = (parse_engine or "").lower()
        if "ragflow" not in engine_l and "deepdoc" not in engine_l:
            result["error"] = f"parse_engine_not_ragflow:{parse_engine or 'missing'}"
            _write_artifact(result)
            print(f"FAIL: expected ragflow/deepdoc parse_engine, got {parse_engine!r}")
            return 1

        gs = client.post(
            "/gateway/search",
            headers=headers,
            json={"query": QUERY, "top_k": 10, "domain": "hybrid"},
        )
        results = gs.json().get("results", []) if gs.status_code == 200 else []
        hit_before = any(str(r.get("document_id")) in doc_ids for r in results)
        if not hit_before:
            hit_before = any(
                "quality" in str(r.get("content", "")).lower()
                or "品質" in str(r.get("content", ""))
                or "ISO" in str(r.get("content", ""))
                for r in results
            )
        result["search_hit_before"] = hit_before
        print(f"search before revoke: {gs.status_code} results={len(results)} hit={hit_before}")
        if not hit_before:
            result["error"] = "no_search_hit_before_revoke"
            _write_artifact(result)
            return 1

        target_doc = doc_ids[0]
        deleted = client.delete(f"/documents/{target_doc}", headers=headers)
        print(f"revoke/delete: {deleted.status_code}")
        if deleted.status_code != 200:
            result["error"] = deleted.text[:200]
            _write_artifact(result)
            return 1

        got = client.get(f"/documents/{target_doc}", headers=headers)
        result["get_after_revoke"] = got.status_code
        print(f"get after revoke: {got.status_code} (expect 404)")
        if got.status_code != 404:
            result["error"] = "document_still_readable"
            _write_artifact(result)
            return 1

        gs2 = client.post(
            "/gateway/search",
            headers=headers,
            json={"query": QUERY, "top_k": 10, "domain": "hybrid"},
        )
        results2 = gs2.json().get("results", []) if gs2.status_code == 200 else []
        leak = [r for r in results2 if str(r.get("document_id")) == target_doc]
        result["search_leak_after"] = len(leak)
        print(f"search after revoke: leak={len(leak)}")
        if leak:
            result["error"] = "revoked_document_leaked_in_search"
            _write_artifact(result)
            return 1

        result["status"] = "PASS"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_artifact(result)
        print("\nRESULT: PASS — NAS → RAGFlow path → index → search → revoke → deny")
        print(f"artifact: {ARTIFACT}")
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        _write_artifact(result)
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
