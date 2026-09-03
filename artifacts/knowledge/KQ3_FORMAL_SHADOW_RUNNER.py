#!/usr/bin/env python3
"""Execute the frozen KQ3 production Shadow gate without tenant mutations."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.inspection import inspect as sa_inspect

from app.config import settings
from app.core.authorization import AuthorizationContext
from app.db.session import SessionLocal, engine
from app.models.audit import UsageRecord
from app.models.chat import Conversation, Message, RetrievalTrace
from app.models.document import Document, DocumentChunk
from app.models.feedback import ChatFeedback
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.mka import KnowhowCardModel
from app.models.user import User
from app.services.chat_orchestrator import ChatOrchestrator
from app.services.knowledge_decision_shadow import EncryptedAppendOnlyShadowStore
from app.services.read_only_barrier import process_read_only


def _canonical(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _rows_digest(rows: list[Any]) -> dict[str, Any]:
    encoded: list[str] = []
    for row in rows:
        columns = sa_inspect(type(row)).columns
        encoded.append("|".join(_canonical(getattr(row, col.key)) for col in columns))
    encoded.sort()
    return {
        "count": len(encoded),
        "sha256": hashlib.sha256("\n".join(encoded).encode("utf-8")).hexdigest(),
    }


def _tenant_digest(tenant_id: UUID) -> dict[str, Any]:
    db = SessionLocal()
    try:
        conversations = db.query(Conversation).filter(Conversation.tenant_id == tenant_id)
        conversation_ids = [row[0] for row in conversations.with_entities(Conversation.id).all()]
        kb_ids = [
            row[0]
            for row in db.query(KnowledgeBase.id)
            .filter(KnowledgeBase.tenant_id == tenant_id)
            .all()
        ]
        queries = {
            "documents": db.query(Document).filter(Document.tenant_id == tenant_id),
            "document_chunks": db.query(DocumentChunk).join(Document).filter(Document.tenant_id == tenant_id),
            "knowledge_base_revisions": db.query(KnowledgeBaseRevision).filter(
                KnowledgeBaseRevision.kb_id.in_(kb_ids)
            ),
            "knowhow_cards": db.query(KnowhowCardModel).filter(KnowhowCardModel.tenant_id == tenant_id),
            "conversations": conversations,
            "messages": db.query(Message).filter(Message.conversation_id.in_(conversation_ids)),
            "retrieval_traces": db.query(RetrievalTrace).filter(RetrievalTrace.tenant_id == tenant_id),
            "chat_feedbacks": db.query(ChatFeedback).filter(ChatFeedback.tenant_id == tenant_id),
            "usage_records": db.query(UsageRecord).filter(UsageRecord.tenant_id == tenant_id),
        }
        payload = {name: _rows_digest(query.all()) for name, query in queries.items()}
        payload["digest"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return payload
    finally:
        db.close()


def _context_digest(context: dict[str, Any]) -> str:
    retrieval = context.get("retrieval") or {}
    refusal = context.get("refusal") or retrieval.get("refusal") or {}
    payload = {
        "has_policy": bool(context.get("has_policy")),
        "evidence_contract": context.get("evidence_contract") or {},
        "sources": [
            {
                "document_id": source.get("document_id"),
                "document_revision": source.get("document_revision"),
                "type": source.get("type"),
                "accessible": source.get("accessible"),
            }
            for source in context.get("sources") or []
        ],
        "context_hashes": [
            hashlib.sha256(str(part).encode("utf-8")).hexdigest()
            for part in context.get("context_parts") or []
        ],
        "retrieval": {
            "mode": retrieval.get("mode"),
            "degraded": retrieval.get("degraded"),
            "query_plan": retrieval.get("query_plan"),
            "label": retrieval.get("label"),
        },
        "refusal_reason": refusal.get("reason"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))
    return round(ordered[index], 6)


def _validate_inputs(cases: dict[str, Any], runtime: dict[str, Any], thresholds: dict[str, Any]) -> None:
    if cases.get("immutable") is not True or cases.get("status") != "FROZEN":
        raise ValueError("case manifest must be frozen and immutable")
    rows = cases.get("cases") or []
    minimum = int(thresholds["case_manifest"]["minimum_cases"])
    if len(rows) < minimum:
        raise ValueError(f"requires at least {minimum} cases")
    subjects = {str(row.get("subject_id")) for row in rows}
    if len(subjects) < int(thresholds["case_manifest"]["minimum_distinct_subjects"]):
        raise ValueError("not enough distinct subjects")
    negatives = sum(bool(row.get("forbidden_document_ids")) for row in rows)
    if negatives < int(thresholds["case_manifest"]["minimum_deny_or_forbidden_cases"]):
        raise ValueError("not enough forbidden cases")
    binding = cases["release_binding"]
    for key in ("release_id", "source_commit", "deployment_manifest_id", "backend_image_id", "frontend_image_id"):
        if binding.get(key) != runtime.get(key):
            raise ValueError(f"runtime binding mismatch: {key}")


async def _retrieve(case: dict[str, Any], channel: str, shadow: bool) -> dict[str, Any]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == UUID(case["subject_id"])).one()
        authz = AuthorizationContext.from_user(user)
        settings.KNOWLEDGE_DECISION_MODE = "shadow" if shadow else "off"
        return await ChatOrchestrator().retrieve_context(
            tenant_id=user.tenant_id,
            question=case["query"],
            authz=authz,
            use_gateway=False,
            db=db,
            decision_channel=channel,
        )
    finally:
        db.close()


async def _run(cases: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases["cases"]:
        baseline = await _retrieve(case, "sync", False)
        sync = await _retrieve(case, "sync", True)
        stream = await _retrieve(case, "stream", True)
        sync_shadow = sync.get("knowledge_decision_shadow") or {}
        stream_shadow = stream.get("knowledge_decision_shadow") or {}
        source_ids = {
            str(source.get("document_id"))
            for source in sync.get("sources") or []
            if source.get("document_id")
        }
        expected = {str(value) for value in case.get("expected_document_ids") or []}
        forbidden = {str(value) for value in case.get("forbidden_document_ids") or []}
        baseline_digest = _context_digest(baseline)
        sync_digest = _context_digest(sync)
        results.append(
            {
                "case_id": case["case_id"],
                "query_hash": hashlib.sha256(case["query"].encode("utf-8")).hexdigest(),
                "subject_ref": hashlib.sha256(case["subject_id"].encode("utf-8")).hexdigest()[:24],
                "baseline_unchanged": baseline_digest == sync_digest,
                "expected_documents_present": expected.issubset(source_ids),
                "forbidden_documents_absent": not bool(forbidden.intersection(source_ids)),
                "telemetry_written": (
                    sync_shadow.get("telemetry_status") == "written"
                    and stream_shadow.get("telemetry_status") == "written"
                ),
                "execution_ok": (
                    sync_shadow.get("execution_status") == "ok"
                    and stream_shadow.get("execution_status") == "ok"
                ),
                "sync_stream_parity": (
                    sync_shadow.get("decision_hash")
                    and sync_shadow.get("decision_hash") == stream_shadow.get("decision_hash")
                ),
                "legacy_decision": sync_shadow.get("legacy_decision"),
                "new_evidence_state": sync_shadow.get("evidence_state"),
                "new_response_action": sync_shadow.get("response_action"),
                "transition": sync_shadow.get("transition"),
                "false_accept_candidate": bool(sync_shadow.get("false_accept_candidate")),
                "false_reject_candidate": bool(sync_shadow.get("false_reject_candidate")),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--thresholds", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--store-path", required=True)
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    runtime = json.loads(Path(args.runtime).read_text(encoding="utf-8"))
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    _validate_inputs(cases, runtime, thresholds)

    tenant_id = UUID(cases["tenant_id"])
    expected_subjects = {row["subject_id"]: row for row in cases["subjects"]}
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.id.in_([UUID(value) for value in expected_subjects])).all()
        actual = {
            str(user.id): {
                "role": user.role,
                "department_id": str(user.department_id) if user.department_id else None,
                "tenant_id": str(user.tenant_id),
            }
            for user in users
        }
    finally:
        db.close()
    for subject_id, expected in expected_subjects.items():
        if actual.get(subject_id) != {
            "role": expected["role"],
            "department_id": expected.get("department_id"),
            "tenant_id": cases["tenant_id"],
        }:
            raise ValueError(f"subject binding mismatch: {subject_id}")

    settings.REDIS_HOST = ""
    settings.KNOWLEDGE_DECISION_TENANT_ALLOWLIST = str(tenant_id)
    settings.KNOWLEDGE_DECISION_KILL_SWITCH = False
    settings.KNOWLEDGE_DECISION_SHADOW_STORE_PATH = args.store_path
    store = EncryptedAppendOnlyShadowStore(args.store_path)
    existing = store.read_for_tenant(tenant_id, actor_roles=["auditor"])
    existing_ids = {str(row.get("record_id")) for row in existing}

    before = _tenant_digest(tenant_id)
    with process_read_only(engine):
        rows = asyncio.run(_run(cases))
    after = _tenant_digest(tenant_id)
    stored = [
        row
        for row in store.read_for_tenant(tenant_id, actor_roles=["auditor"])
        if str(row.get("record_id")) not in existing_ids
    ]

    sync_records = [row for row in stored if row.get("channel") == "sync"]
    valid = [row for row in rows if row["telemetry_written"] and row["execution_ok"]]
    # Transition flags are triage candidates only.  Formal error rates are
    # adjudicated against the case manifest's frozen expected/forbidden docs.
    false_accepts = sum(
        row["new_evidence_state"] == "complete"
        and not row["expected_documents_present"]
        for row in valid
    )
    false_rejects = sum(
        row["new_evidence_state"] != "complete"
        and row["expected_documents_present"]
        for row in valid
    )
    false_accept_rate = false_accepts / len(valid) if valid else None
    false_reject_rate = false_rejects / len(valid) if valid else None
    parity = sum(bool(row["sync_stream_parity"]) for row in valid) / len(valid) if valid else 0.0
    execution_failure_rate = 1.0 - (len(valid) / len(rows)) if rows else 1.0
    overhead = []
    for record in stored:
        latency = record.get("stage_latency_ms") or {}
        values = [latency.get(stage) for stage in ("parse", "select", "applicability", "completeness", "conversation")]
        if all(isinstance(value, (int, float)) for value in values):
            overhead.append(sum(float(value) for value in values))
    overhead_summary = {
        "p50": _percentile(overhead, 0.50),
        "p95": _percentile(overhead, 0.95),
        "p99": _percentile(overhead, 0.99),
    }
    transition_matrix = dict(sorted(Counter(row.get("transition") or "unknown" for row in valid).items()))
    quality = thresholds["quality_thresholds"]
    latency_limits = thresholds["latency_overhead_ms"]
    checks = {
        "tenant_mutation_zero": before == after,
        "minimum_cases": len(rows) >= int(thresholds["case_manifest"]["minimum_cases"]),
        "minimum_subjects": len({row["subject_ref"] for row in rows}) >= int(thresholds["case_manifest"]["minimum_distinct_subjects"]),
        "forbidden_cases": sum(bool(case.get("forbidden_document_ids")) for case in cases["cases"]) >= int(thresholds["case_manifest"]["minimum_deny_or_forbidden_cases"]),
        "expected_documents": all(row["expected_documents_present"] for row in rows),
        "forbidden_absence": all(row["forbidden_documents_absent"] for row in rows),
        "legacy_answer_unchanged": all(row["baseline_unchanged"] for row in rows),
        "telemetry_record_count": len(stored) == len(rows) * 2 and len(sync_records) == len(rows),
        "false_accept_rate": false_accept_rate is not None and false_accept_rate <= float(quality["maximum_false_accept_rate"]),
        "false_reject_rate": false_reject_rate is not None and false_reject_rate <= float(quality["maximum_false_reject_rate"]),
        "execution_failure_rate": execution_failure_rate <= float(quality["maximum_execution_failure_rate"]),
        "sync_stream_parity": parity >= float(quality["minimum_sync_stream_decision_parity"]),
        "latency_overhead": all(
            overhead_summary[name] is not None and overhead_summary[name] <= float(latency_limits[name])
            for name in ("p50", "p95", "p99")
        ),
    }
    report = {
        "schema_version": "kq3-formal-shadow-report.v1",
        "gate": "KQ-SHADOW-01",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "case_manifest_sha256": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),
        "threshold_manifest_sha256": hashlib.sha256(Path(args.thresholds).read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime": runtime,
        "tenant_ref": hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:24],
        "before": before,
        "after": after,
        "unexpected_writes": 0 if before == after else 1,
        "metrics": {
            "cases": len(rows),
            "valid_cases": len(valid),
            "stored_records": len(stored),
            "false_accept_rate": false_accept_rate,
            "false_reject_rate": false_reject_rate,
            "false_accept_candidates": sum(row["false_accept_candidate"] for row in valid),
            "false_reject_candidates": sum(row["false_reject_candidate"] for row in valid),
            "execution_failure_rate": execution_failure_rate,
            "sync_stream_parity": parity,
            "decision_overhead_ms": overhead_summary,
            "transition_matrix": transition_matrix,
        },
        "checks": checks,
        "cases": rows,
    }
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
