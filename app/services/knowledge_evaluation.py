"""Immutable evaluation registry and deterministic quality summaries."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from app.eval.metrics import wilson_interval
from app.models.knowledge_engine import EvaluationCaseResult, EvaluationRun


def evaluation_key(*, split: str, corpus_hash: str, question_hash: str, scoring_hash: str) -> str:
    body = {"split": split, "corpus_hash": corpus_hash, "question_hash": question_hash, "scoring_hash": scoring_hash}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def start_run(db, *, tenant_id, split: str, corpus_hash: str, question_hash: str,
              scoring_hash: str, runtime_manifest: Mapping[str, Any]) -> EvaluationRun:
    key = evaluation_key(split=split, corpus_hash=corpus_hash, question_hash=question_hash, scoring_hash=scoring_hash)
    baseline = db.query(EvaluationRun).filter(
        EvaluationRun.evaluation_key == key,
        EvaluationRun.first_run.is_(True),
    ).order_by(EvaluationRun.created_at.asc()).first()
    row = EvaluationRun(
        tenant_id=tenant_id,
        split=split,
        evaluation_key=key,
        corpus_hash=corpus_hash,
        question_hash=question_hash,
        scoring_hash=scoring_hash,
        runtime_manifest=dict(runtime_manifest),
        first_run=baseline is None,
        baseline_run_id=baseline.id if baseline else None,
        status="running",
    )
    db.add(row)
    db.flush()
    return row


def add_results(db, run: EvaluationRun, results: Iterable[Mapping[str, Any]]) -> int:
    if run.status != "running":
        raise ValueError("completed evaluation evidence is immutable")
    count = 0
    for item in results:
        verdict = str(item["verdict"]).upper()
        if verdict not in {"PASS", "FAIL", "BLOCKED", "SKIPPED", "REVIEW"}:
            raise ValueError(f"unsupported evaluation verdict: {verdict}")
        db.add(EvaluationCaseResult(
            run_id=run.id,
            case_id=str(item["case_id"]),
            domain=str(item.get("domain") or "unknown"),
            case_type=str(item.get("case_type") or "unknown"),
            verdict=verdict,
            critical_error=bool(item.get("critical_error", False)),
            metrics_json=dict(item.get("metrics") or {}),
            evidence_digest=item.get("evidence_digest"),
        ))
        count += 1
    db.flush()
    return count


def finalize_run(db, run: EvaluationRun) -> dict[str, Any]:
    if run.status != "running":
        raise ValueError("completed evaluation evidence is immutable")
    results = db.query(EvaluationCaseResult).filter(EvaluationCaseResult.run_id == run.id).all()
    counts = Counter(result.verdict for result in results)
    strict_total = counts["PASS"] + counts["FAIL"]
    low, high = wilson_interval(counts["PASS"], strict_total) if strict_total else (0.0, 0.0)
    domains = Counter(result.domain for result in results)
    case_types = Counter(result.case_type for result in results)
    domain_quality = {}
    for domain in sorted(domains):
        domain_results = [result for result in results if result.domain == domain and result.verdict in {"PASS", "FAIL"}]
        passed = sum(1 for result in domain_results if result.verdict == "PASS")
        domain_quality[domain] = {"numerator": passed, "denominator": len(domain_results),
                                  "rate": passed / len(domain_results) if domain_results else None}
    slot_num = sum(int((result.metrics_json or {}).get("required_slots_covered", 0)) for result in results)
    slot_den = sum(int((result.metrics_json or {}).get("required_slots_total", 0)) for result in results)
    language_profiles = Counter(
        str((result.metrics_json or {}).get("language_profile") or "standard")
        for result in results
    )
    summary = {
        "total": len(results),
        "verdict_counts": {key: counts[key] for key in ("PASS", "FAIL", "BLOCKED", "SKIPPED", "REVIEW")},
        "strict_assertions": {
            "numerator": counts["PASS"],
            "denominator": strict_total,
            "rate": counts["PASS"] / strict_total if strict_total else None,
            "wilson_95": [low, high],
        },
        "critical_errors": sum(1 for result in results if result.critical_error),
        "domain_distribution": dict(sorted(domains.items())),
        "domain_quality": domain_quality,
        "case_type_distribution": dict(sorted(case_types.items())),
        "language_profile_distribution": dict(sorted(language_profiles.items())),
        "required_slot_coverage": {"numerator": slot_num, "denominator": slot_den,
                                   "rate": slot_num / slot_den if slot_den else None},
    }
    run.summary_json = summary
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    return summary
