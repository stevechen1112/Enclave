"""A2 / CV-INT: fail the build when Enclave claims a parser it did not run.

Two layers of checking:

Static  - source must not hardcode a ragflow/deepdoc label or derive ocr_used from
          the Enclave route instead of the upstream layout_recognize value.
Dynamic - for every document in the database whose quality_report claims deepdoc,
          the live RAGFlow dataset must actually have layout_recognize=DeepDOC.

Usage:
  python scripts/eval_label_integrity.py            # static + dynamic when reachable
  python scripts/eval_label_integrity.py --static-only
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "label_integrity_last_run.json"

BASE = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/")
KEY = os.getenv("RAGFLOW_API_KEY", "")

SOURCE_GLOBS = ("app/services/*.py", "app/tasks/*.py", "app/gateway/adapters/*.py")

# A literal deepdoc label assigned to a variable is the exact defect A1 removed:
# it claims DeepDoc ran without consulting the upstream layout_recognize value.
HARDCODED_LABEL = re.compile(r'=\s*["\']ragflow/deepdoc["\']')
# ocr_used must not be derived from the Enclave route enum.
ROUTE_DERIVED_OCR = re.compile(r'ocr_used\s*=\s*route\s*==')


def ragflow_get(path: str):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def static_scan() -> list[dict]:
    findings = []
    for pattern in SOURCE_GLOBS:
        for path in ROOT.glob(pattern):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if HARDCODED_LABEL.search(line):
                    findings.append({
                        "type": "hardcoded_deepdoc_label",
                        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "line": lineno,
                        "text": stripped[:160],
                    })
                if ROUTE_DERIVED_OCR.search(line):
                    findings.append({
                        "type": "ocr_used_derived_from_route",
                        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "line": lineno,
                        "text": stripped[:160],
                    })
    return findings


def dynamic_scan() -> tuple[list[dict], dict]:
    """Cross-check claimed engines in the DB against live RAGFlow dataset settings."""
    findings: list[dict] = []
    context: dict = {}
    try:
        from sqlalchemy import create_engine, text as sql_text
    except ImportError:
        return findings, {"skipped": "sqlalchemy unavailable"}

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        host = os.getenv("POSTGRES_SERVER")
        db = os.getenv("POSTGRES_DB")
        user = os.getenv("POSTGRES_USER")
        if not (host and db and user):
            return findings, {"skipped": "no database connection settings"}
        db_url = (f"postgresql://{user}:{os.getenv('POSTGRES_PASSWORD', '')}"
                  f"@{host}:{os.getenv('POSTGRES_PORT', '5432')}/{db}")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        datasets = ragflow_get("/api/v1/datasets?page=1&page_size=100").get("data") or []
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return findings, {"skipped": f"ragflow unreachable: {exc}"}

    layouts = {
        ds["id"]: (ds.get("parser_config") or {}).get("layout_recognize")
        for ds in datasets
    }
    # Only the configured production dataset counts. A throwaway evaluation dataset
    # that happens to use DeepDOC must never launder a stale deepdoc label.
    production_dataset = os.getenv("RAGFLOW_DATASET_ID", "")
    production_layout = layouts.get(production_dataset)
    production_is_deepdoc = str(production_layout).strip().lower() == "deepdoc"
    context["dataset_layouts"] = layouts
    context["production_dataset_id"] = production_dataset
    context["production_layout_recognize"] = production_layout

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(sql_text(
                "SELECT id, filename, quality_report FROM documents "
                "WHERE quality_report IS NOT NULL LIMIT 2000"
            )).fetchall()
    except Exception as exc:
        return findings, {"skipped": f"db unreachable: {type(exc).__name__}"}

    claimed_deepdoc = 0
    for row in rows:
        report = row[2]
        if isinstance(report, str):
            try:
                report = json.loads(report)
            except json.JSONDecodeError:
                continue
        if not isinstance(report, dict):
            continue
        engine_label = str(report.get("parse_engine") or report.get("parser") or "")
        if "deepdoc" not in engine_label.lower():
            continue
        claimed_deepdoc += 1

        recorded_layout = report.get("layout_recognize_actual")
        if recorded_layout is not None:
            # Post-A1 documents carry provenance and can be checked directly.
            if str(recorded_layout).strip().lower() != "deepdoc":
                findings.append({
                    "type": "deepdoc_label_contradicts_recorded_layout",
                    "document_id": str(row[0]),
                    "filename": row[1],
                    "claimed_engine": engine_label,
                    "layout_recognize_actual": recorded_layout,
                })
        elif not production_is_deepdoc:
            # Pre-A1 documents have no provenance; the label is only credible if the
            # dataset they were ingested into is itself running DeepDOC.
            findings.append({
                "type": "deepdoc_label_without_provenance_on_non_deepdoc_dataset",
                "document_id": str(row[0]),
                "filename": row[1],
                "claimed_engine": engine_label,
                "production_layout_recognize": production_layout,
            })

    context.update({
        "documents_checked": len(rows),
        "documents_claiming_deepdoc": claimed_deepdoc,
        "production_is_deepdoc": production_is_deepdoc,
    })
    return findings, context


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static-only", action="store_true")
    args = ap.parse_args()

    static_findings = static_scan()
    dynamic_findings, context = ([], {"skipped": "--static-only"}) if args.static_only else dynamic_scan()

    findings = static_findings + dynamic_findings
    report = {
        "gate": "CV-INT",
        "status": "FAIL" if findings else "PASS",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": {
            "static_source_scan": {"violations": len(static_findings)},
            "dynamic_db_vs_ragflow": {"violations": len(dynamic_findings), **context},
        },
        "findings": findings,
        "rule": "parse_engine must reflect upstream layout_recognize; "
                "ocr_used must reflect what RAGFlow ran, not the Enclave route.",
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"static violations : {len(static_findings)}")
    print(f"dynamic violations: {len(dynamic_findings)}  {context}")
    for f in findings[:20]:
        print(f"  [{f['type']}] {f.get('file') or f.get('filename')}:{f.get('line', '')} {f.get('text', '')}")
    print(f"status = {report['status']}")
    print(f"written: {ARTIFACT}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
