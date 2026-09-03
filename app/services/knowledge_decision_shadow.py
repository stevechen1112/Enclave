"""KQ3 read-only shadow adapter and out-of-band encrypted telemetry store."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.services.evidence_contract import (
    AnswerRequirement,
    EvidenceContract,
    EvidenceItem,
    ExecutionStatus,
    ReviewedScope,
)
from app.services.evidence_orchestrator import EvidenceDecision, decide_evidence
from app.services.retrieval_coverage import SLOT_RULES

SHADOW_SCHEMA_VERSION = "kq-shadow.v1"
_WRITE_LOCK = threading.Lock()
_VALUE_TYPES = {
    "unit_price": "money",
    "total_price": "money",
    "amount": "money",
    "date": "date",
    "delivery_date": "date",
    "quantity": "quantity",
    "status": "status",
    "steps": "list",
    "procedure": "list",
    "actor": "name",
    "revision": "code",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tenant_ref(tenant_id: Any) -> str:
    return hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:24]


def _fernet_key(configured: str = "") -> bytes:
    value = str(configured or "").strip().encode("utf-8")
    if value:
        try:
            Fernet(value)
            return value
        except (ValueError, TypeError):
            pass
    secret = str(getattr(settings, "SECRET_KEY", "") or "").encode("utf-8")
    if not secret:
        raise ValueError("shadow encryption key is not configured")
    return base64.urlsafe_b64encode(hashlib.sha256(secret).digest())


def resolve_knowledge_decision_mode(
    tenant_id: Any, *, request_id: str | None = None
) -> str:
    if bool(getattr(settings, "KNOWLEDGE_DECISION_KILL_SWITCH", False)):
        return "off"
    mode = str(getattr(settings, "KNOWLEDGE_DECISION_MODE", "off") or "off").lower()
    allowlist = {
        token.strip()
        for token in str(
            getattr(settings, "KNOWLEDGE_DECISION_TENANT_ALLOWLIST", "") or ""
        ).split(",")
        if token.strip()
    }
    if str(tenant_id) not in allowlist:
        return "off"
    if mode not in {"shadow", "enforce"}:
        return "off"
    # KQ7 uses a distinct signed Owner record for each transition. Allowlist,
    # platform gates and earlier shadow approval never imply enforce approval.
    if bool(getattr(settings, "KNOWLEDGE_DECISION_AUTHORIZATION_REQUIRED", True)):
        from app.services.knowledge_release_control import requested_mode_is_authorized

        return (
            mode
            if requested_mode_is_authorized(
                str(tenant_id), mode, request_id=request_id
            )
            else "off"
        )
    # Technical rollout is controlled by mode + tenant allowlist + kill switch.
    # Signed authorization remains an optional governance integration only.
    return mode


@dataclass(frozen=True)
class ShadowDiffRecord:
    record_id: str
    schema_version: str
    captured_at: str
    tenant_ref: str
    request_ref: str
    channel: str
    legacy_decision: str
    new_evidence_state: str
    new_response_action: str
    execution_status: str
    decision_hash: str
    transition: str
    false_accept_candidate: bool
    false_reject_candidate: bool
    stage_trace: list[dict[str, Any]]
    reason_codes: list[str]
    source_refs: list[dict[str, Any]]
    stage_latency_ms: dict[str, float | None]
    supersedes_record_id: str | None = None
    retention_class: str = "knowledge_shadow_30d"
    legal_hold: bool = False


class EncryptedAppendOnlyShadowStore:
    """Local out-of-band JSONL segments encrypted with Fernet at rest."""

    def __init__(self, root: str | Path | None = None, *, key: str = ""):
        configured_root = root or getattr(
            settings, "KNOWLEDGE_DECISION_SHADOW_STORE_PATH", "artifacts/knowledge/kq_shadow"
        )
        self.root = Path(configured_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_fernet_key(key or getattr(settings, "KNOWLEDGE_DECISION_SHADOW_KEY", "")))

    def _segment(self, captured_at: str) -> Path:
        day = captured_at[:10]
        return self.root / f"shadow-{day}.jsonl.enc"

    def append(self, record: ShadowDiffRecord) -> Path:
        path = self._segment(record.captured_at)
        prefix = f"{record.record_id} ".encode("ascii")
        payload = json.dumps(asdict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")
        line = prefix + self._fernet.encrypt(payload) + b"\n"
        with _WRITE_LOCK:
            if path.exists():
                with path.open("rb") as existing:
                    if any(row.startswith(prefix) for row in existing):
                        raise ValueError("append-only record_id already exists")
            with path.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        return path

    def read_for_tenant(
        self,
        tenant_id: Any,
        *,
        actor_roles: Iterable[str],
        source_authorizer: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        if not {str(role) for role in actor_roles}.intersection({"admin", "auditor"}):
            raise PermissionError("shadow telemetry requires admin or auditor")
        expected = _tenant_ref(tenant_id)
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("shadow-*.jsonl.enc")):
            for line in path.read_bytes().splitlines():
                try:
                    _, token = line.split(b" ", 1)
                    item = json.loads(self._fernet.decrypt(token))
                except (ValueError, InvalidToken, json.JSONDecodeError):
                    continue
                if item.get("tenant_ref") != expected:
                    continue
                if source_authorizer is not None:
                    item["source_refs"] = [
                        ref for ref in item.get("source_refs") or [] if source_authorizer(ref)
                    ]
                records.append(item)
        return records

    def purge_expired(
        self,
        *,
        now: datetime | None = None,
        retention_days: int | None = None,
        legal_hold_record_ids: Iterable[str] = (),
    ) -> list[str]:
        """Purge expired segments and append a content-free audit event."""
        point = now or _now()
        days = retention_days or int(
            getattr(settings, "KNOWLEDGE_DECISION_SHADOW_RETENTION_DAYS", 30)
        )
        cutoff = (point - timedelta(days=days)).date()
        holds = set(legal_hold_record_ids)
        purged: list[str] = []
        audit_path = self.root / "purge-audit.jsonl"
        for path in sorted(self.root.glob("shadow-*.jsonl.enc")):
            try:
                day = datetime.fromisoformat(path.stem.removeprefix("shadow-").removesuffix(".jsonl")).date()
            except ValueError:
                continue
            if day >= cutoff:
                continue
            ids = {line.split(b" ", 1)[0].decode("ascii") for line in path.read_bytes().splitlines()}
            if ids.intersection(holds):
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.unlink()
            purged.append(path.name)
            audit = {
                "event": "retention_purge",
                "segment": path.name,
                "segment_sha256": digest,
                "record_count": len(ids),
                "purged_at": point.isoformat(),
            }
            with audit_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(audit, sort_keys=True) + "\n")
        return purged


def _placeholder(slot_id: str) -> tuple[Any, str]:
    value_type = _VALUE_TYPES.get(slot_id, "text")
    if value_type in {"money", "quantity", "ratio"}:
        return 0, value_type
    if value_type == "date":
        return "2000-01-01", value_type
    if value_type == "list":
        return ["verified"], value_type
    return "verified", value_type


def _compile_shadow_inputs(
    *, tenant_id: Any, query_plan: Mapping[str, Any], results: list[Mapping[str, Any]]
) -> tuple[EvidenceContract, list[EvidenceItem]]:
    requested = [str(value) for value in query_plan.get("requested_slots") or []]
    if not requested:
        requested = ["answer"]
    requirements = [
        AnswerRequirement(
            slot_id,
            SLOT_RULES.get(slot_id, (slot_id,))[0],
            _VALUE_TYPES.get(slot_id, "text"),
        )
        for slot_id in requested
    ]
    exhaustive = str(query_plan.get("completeness_mode")) == "exhaustive"
    reviewed_scope = ReviewedScope(tenant_id=str(tenant_id), exhaustive=exhaustive)
    evidence: list[EvidenceItem] = []
    for index, result in enumerate(results):
        content = str(result.get("content") or "")
        metadata = dict(result.get("metadata") or {})
        # Results entering this adapter have already passed the server-owned
        # RetrievalFacade current-revision/ACL checks.  Older providers do not
        # emit the newer authority flags, so absence means "legacy verified";
        # an explicit false value must still fail closed.
        active_revision = (
            bool(metadata["active_revision"])
            if "active_revision" in metadata
            else True
        )
        release_active = (
            bool(metadata["release_active"])
            if "release_active" in metadata
            else True
        )
        quality_ready = (
            bool(metadata["quality_ready"])
            if "quality_ready" in metadata
            else True
        )
        for slot_id in requested:
            rule = SLOT_RULES.get(slot_id)
            if slot_id != "answer" and (rule is None or not rule[1].search(content)):
                continue
            value, value_type = _placeholder(slot_id)
            evidence.append(
                EvidenceItem(
                    slot_id=slot_id,
                    value=value,
                    value_type=value_type,
                    document_id=str(result.get("document_id") or metadata.get("document_id") or ""),
                    document_revision=str(result.get("document_revision") or metadata.get("document_revision") or ""),
                    unit_id=str(result.get("unit_id") or result.get("id") or f"candidate-{index}"),
                    unit_type=str(metadata.get("unit_type") or metadata.get("evidence_kind") or "narrative"),
                    quote=content,
                    entity_id=metadata.get("entity_id"),
                    authority_class=str(metadata.get("authority_class") or "primary_document"),
                    kb_revision_id=metadata.get("kb_revision_id"),
                    acl_verified=metadata.get("accessible") is not False and not metadata.get("denied", False),
                    active_revision=active_revision,
                    tenant_id=str(tenant_id),
                    department_id=metadata.get("department_id"),
                    source_id=str(result.get("document_id") or metadata.get("source_id") or ""),
                    knowledge_release_id=metadata.get("knowledge_release_id"),
                    denied=bool(metadata.get("denied", False)),
                    tombstoned=bool(metadata.get("tombstoned", False)),
                    release_active=release_active,
                    quality_ready=quality_ready,
                )
            )
    return EvidenceContract(requirements, reviewed_scope=reviewed_scope), evidence


def run_knowledge_decision_shadow(
    *,
    tenant_id: Any,
    request_id: str,
    query_plan: Mapping[str, Any],
    results: list[Mapping[str, Any]],
    legacy_coverage: Mapping[str, Any],
    execution_status: ExecutionStatus | str = ExecutionStatus.OK,
    retrieval_latency_ms: float | None = None,
    channel: str = "sync",
    store: EncryptedAppendOnlyShadowStore | None = None,
) -> dict[str, Any]:
    """Run one deterministic shadow case; never raise into the Ask path."""
    mode = resolve_knowledge_decision_mode(tenant_id, request_id=request_id)
    if mode == "off":
        return {"mode": "off", "executed": False, "telemetry_status": "not_attempted"}
    try:
        contract, evidence = _compile_shadow_inputs(
            tenant_id=tenant_id, query_plan=query_plan, results=results
        )
        decision: EvidenceDecision = decide_evidence(
            contract,
            evidence,
            operation=str(query_plan.get("operation") or "lookup"),
            query_spec=query_plan,
            execution_status=execution_status,
        )
        from app.services.answer_plan import build_answer_plan, render_answer_plan

        render_started = time.perf_counter()
        answer_plan = build_answer_plan(decision, query_spec=query_plan)
        rendered_answer = render_answer_plan(answer_plan)
        render_latency_ms = (time.perf_counter() - render_started) * 1000
        legacy = str(legacy_coverage.get("decision") or "abstain")
        transition = f"{legacy}->{decision.evidence_state}"
        source_refs = [
            {
                "document_id": item.document_id,
                "document_revision": item.document_revision,
                "unit_id": item.unit_id,
            }
            for item in [*decision.verified_claims, *decision.near_evidence]
        ]
        stage_latency_ms = {
            str(row["stage"]): row.get("latency_ms") for row in decision.stage_trace
        }
        stage_latency_ms["retrieve"] = retrieval_latency_ms
        stage_latency_ms["render"] = render_latency_ms
        record = ShadowDiffRecord(
            record_id=str(uuid.uuid4()),
            schema_version=SHADOW_SCHEMA_VERSION,
            captured_at=_now().isoformat(),
            tenant_ref=_tenant_ref(tenant_id),
            request_ref=hashlib.sha256(str(request_id).encode("utf-8")).hexdigest()[:24],
            channel="stream" if channel == "stream" else "sync",
            legacy_decision=legacy,
            new_evidence_state=decision.evidence_state,
            new_response_action=decision.response_action,
            execution_status=decision.execution_status,
            decision_hash=decision.decision_hash,
            transition=transition,
            # A newly accepted answer that legacy rejected is a possible false
            # acceptance; a newly rejected answer that legacy accepted is a
            # possible false rejection.  Formal rates still require frozen
            # ground-truth adjudication rather than treating transitions as
            # errors by themselves.
            false_accept_candidate=legacy != "answer" and decision.evidence_state == "complete",
            false_reject_candidate=legacy == "answer" and decision.evidence_state != "complete",
            stage_trace=decision.stage_trace,
            reason_codes=decision.reason_codes,
            source_refs=source_refs,
            stage_latency_ms=stage_latency_ms,
        )
        target_store = store or EncryptedAppendOnlyShadowStore()
        target_store.append(record)
        return {
            "mode": mode,
            "executed": True,
            "telemetry_status": "written",
            "record_id": record.record_id,
            "legacy_decision": legacy,
            "evidence_state": decision.evidence_state,
            "response_action": decision.response_action,
            "execution_status": decision.execution_status,
            "decision_hash": decision.decision_hash,
            "transition": transition,
            "false_accept_candidate": record.false_accept_candidate,
            "false_reject_candidate": record.false_reject_candidate,
            "answer_plan": answer_plan.to_dict(),
            "deterministic_answer": rendered_answer.to_dict(),
        }
    except Exception as exc:
        return {
            "mode": mode,
            "executed": True,
            "telemetry_status": "failed",
            "error_class": type(exc).__name__,
        }


def summarize_shadow_records(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute separate false-accept/reject rates and stage percentiles."""
    rows = [row for row in records if row.get("execution_status") == "ok"]
    denominator = len(rows)
    false_accepts = sum(bool(row.get("false_accept_candidate")) for row in rows)
    false_rejects = sum(bool(row.get("false_reject_candidate")) for row in rows)
    transitions: dict[str, int] = {}
    stage_values: dict[str, list[float]] = {}
    for row in rows:
        transition = str(row.get("transition") or "unknown")
        transitions[transition] = transitions.get(transition, 0) + 1
        for stage, value in dict(row.get("stage_latency_ms") or {}).items():
            if isinstance(value, (int, float)):
                stage_values.setdefault(str(stage), []).append(float(value))

    def percentile(values: list[float], ratio: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = max(
            0,
            min(len(ordered) - 1, int((len(ordered) - 1) * ratio + 0.999999)),
        )
        return ordered[index]

    return {
        "valid_cases": denominator,
        "false_accept_candidates": false_accepts,
        "false_reject_candidates": false_rejects,
        "false_accept_rate": false_accepts / denominator if denominator else None,
        "false_reject_rate": false_rejects / denominator if denominator else None,
        "transition_matrix": dict(sorted(transitions.items())),
        "stage_latency_ms": {
            stage: {
                "p50": percentile(values, 0.50),
                "p95": percentile(values, 0.95),
                "p99": percentile(values, 0.99),
            }
            for stage, values in sorted(stage_values.items())
        },
    }
