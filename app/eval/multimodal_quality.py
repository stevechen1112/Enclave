"""Deterministic multimodal corpus validation and safety-quality gates.

The evaluator intentionally separates contract fixtures from live provider output.
Mock results prove schema and policy behaviour; only replay/live results may be
used as model or parser quality evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_MODES = {"mock_contract", "internal_replay", "degraded"}
TERMINAL_STATES = {
    "completed",
    "completed_no_knowledge",
    "review_required",
    "rejected",
    "degraded",
    "failed_explained",
}


class CorpusValidationError(ValueError):
    """Raised when corpus or result provenance is incomplete."""


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != 1:
        raise CorpusValidationError("manifest.schema_version must be 1")
    if manifest.get("classification") not in {"synthetic", "licensed_internal"}:
        raise CorpusValidationError(
            "manifest.classification must establish legal provenance"
        )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CorpusValidationError("manifest.cases must be a non-empty list")

    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            raise CorpusValidationError(f"case id missing or duplicated: {case_id!r}")
        seen.add(case_id)
        if not case.get("modality") or not case.get("slice"):
            raise CorpusValidationError(f"{case_id}: modality and slice are required")
        source = case.get("source") or {}
        if not source.get("uri") or not source.get("content_type"):
            raise CorpusValidationError(
                f"{case_id}: source uri/content_type are required"
            )
        if not source.get("provenance"):
            raise CorpusValidationError(f"{case_id}: source provenance is required")
        expected = case.get("expected") or {}
        states = set(expected.get("terminal_states") or [])
        if not states or not states <= TERMINAL_STATES:
            raise CorpusValidationError(f"{case_id}: invalid expected terminal_states")
        if not expected.get("tenant_id") or not expected.get("revision_id"):
            raise CorpusValidationError(
                f"{case_id}: tenant_id and revision_id are required"
            )
        for locator in expected.get("evidence_locators") or []:
            if not locator.get("id") or not locator.get("kind"):
                raise CorpusValidationError(f"{case_id}: locator id/kind are required")
            if locator.get("kind") in {"audio", "video"}:
                start = locator.get("start_ms")
                end = locator.get("end_ms")
                if (
                    not isinstance(start, int)
                    or not isinstance(end, int)
                    or start < 0
                    or end <= start
                ):
                    raise CorpusValidationError(f"{case_id}: invalid time locator")
    return cases


def validate_results(
    results: dict[str, Any], case_ids: set[str]
) -> list[dict[str, Any]]:
    mode = results.get("mode")
    if mode not in SUPPORTED_MODES:
        raise CorpusValidationError(f"unsupported provider mode: {mode!r}")
    if not results.get("provider") or not results.get("provider_version"):
        raise CorpusValidationError("provider and provider_version are required")
    if not results.get("corpus_sha256"):
        raise CorpusValidationError("results must be bound to corpus_sha256")
    if mode == "internal_replay":
        provenance = results.get("provenance") or {}
        if not provenance.get("run_id") or not provenance.get("captured_at"):
            raise CorpusValidationError(
                "internal_replay requires run_id and captured_at"
            )
        if not re.fullmatch(
            r"[0-9a-f]{40}", str(provenance.get("source_commit") or "")
        ):
            raise CorpusValidationError(
                "internal_replay source_commit must be 40 lowercase hex"
            )
        if not provenance.get("execution_environment") or not provenance.get(
            "source_artifact_sha256"
        ):
            raise CorpusValidationError(
                "internal_replay requires execution environment and source artifact hash"
            )
    rows = results.get("results")
    if not isinstance(rows, list):
        raise CorpusValidationError("results.results must be a list")
    seen: set[str] = set()
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id not in case_ids or case_id in seen:
            raise CorpusValidationError(
                f"unknown or duplicated result case: {case_id!r}"
            )
        seen.add(case_id)
        if row.get("terminal_state") not in TERMINAL_STATES:
            raise CorpusValidationError(f"{case_id}: invalid terminal state")
    missing = case_ids - seen
    if missing:
        raise CorpusValidationError(f"missing result cases: {sorted(missing)}")
    return rows


def _locator_matches(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    """Match stable source coordinates, never run-specific database IDs."""
    if expected.get("kind") != predicted.get("kind"):
        return False
    if expected.get("revision_id") != predicted.get("revision_id"):
        return False
    kind = expected.get("kind")
    if kind in {"audio", "video"}:
        expected_start, expected_end = expected.get("start_ms"), expected.get("end_ms")
        predicted_start, predicted_end = predicted.get("start_ms"), predicted.get(
            "end_ms"
        )
        if not all(
            isinstance(value, int)
            for value in (expected_start, expected_end, predicted_start, predicted_end)
        ):
            return False
        overlap = max(
            0, min(expected_end, predicted_end) - max(expected_start, predicted_start)
        )
        union = max(expected_end, predicted_end) - min(expected_start, predicted_start)
        return bool(union and overlap / union >= 0.5)
    coordinate_fields = (
        "page",
        "section",
        "worksheet",
        "table_name",
        "cell_range",
        "row_number",
        "column_name",
        "region",
    )
    return all(
        expected.get(field) == predicted.get(field)
        for field in coordinate_fields
        if field in expected or field in predicted
    )


def _locator_match_count(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> int:
    remaining = list(predicted)
    matches = 0
    for expected_item in expected:
        for index, predicted_item in enumerate(remaining):
            if _locator_matches(expected_item, predicted_item):
                matches += 1
                remaining.pop(index)
                break
    return matches


@dataclass(frozen=True)
class Thresholds:
    terminal_state_rate_min: float = 0.98
    evidence_locator_precision_min: float = 0.95
    evidence_locator_recall_min: float = 0.95
    critical_error_max: int = 0

    @classmethod
    def from_dict(cls, values: dict[str, Any] | None) -> Thresholds:
        values = values or {}
        return cls(
            **{key: values[key] for key in cls.__dataclass_fields__ if key in values}
        )


def evaluate(
    manifest: dict[str, Any],
    result_bundle: dict[str, Any],
    thresholds: Thresholds | None = None,
) -> dict[str, Any]:
    cases = validate_manifest(manifest)
    corpus_sha256 = canonical_hash(manifest)
    rows = validate_results(result_bundle, {case["id"] for case in cases})
    if result_bundle["corpus_sha256"] != corpus_sha256:
        raise CorpusValidationError("result corpus_sha256 does not match manifest")
    thresholds = thresholds or Thresholds()
    by_id = {row["case_id"]: row for row in rows}

    valid_terminal = 0
    expected_locator_count = 0
    predicted_locator_count = 0
    correct_locator_count = 0
    hallucinations = 0
    wrong_revision = 0
    low_confidence_unreviewed = 0
    unsafe_high_risk_answers = 0
    sop_conflict_misses = 0
    cross_tenant_leaks = 0
    per_slice: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for case in cases:
        expected = case["expected"]
        row = by_id[case["id"]]
        slice_key = f'{case["modality"]}:{case["slice"]}'
        per_slice[slice_key]["total"] += 1
        if row["terminal_state"] in set(expected["terminal_states"]):
            valid_terminal += 1
            per_slice[slice_key]["terminal_pass"] += 1

        expected_locators = expected.get("evidence_locators") or []
        predicted_locators = row.get("evidence_locators") or []
        expected_locator_count += len(expected_locators)
        predicted_locator_count += len(predicted_locators)
        matches = _locator_match_count(expected_locators, predicted_locators)
        correct_locator_count += matches
        per_slice[slice_key]["locator_expected"] += len(expected_locators)
        per_slice[slice_key]["locator_predicted"] += len(predicted_locators)
        per_slice[slice_key]["locator_correct"] += matches

        answer = row.get("answer") or {}
        citations = answer.get("citations") or []
        if answer.get("status") == "answered" and (
            not answer.get("grounded", False) or not citations
        ):
            hallucinations += 1
        if any(
            item.get("revision_id") != expected["revision_id"] for item in citations
        ):
            wrong_revision += 1
        if (
            expected.get("high_risk")
            and answer.get("status") == "answered"
            and not answer.get("authoritative", False)
        ):
            unsafe_high_risk_answers += 1
        if expected.get("low_confidence") and not row.get("review_created", False):
            low_confidence_unreviewed += 1
        if (
            expected.get("sop_conflict")
            and row["terminal_state"] != "degraded"
            and not row.get("sop_conflict_detected", False)
        ):
            sop_conflict_misses += 1
        if row.get("tenant_id") != expected["tenant_id"]:
            cross_tenant_leaks += 1
        cross_tenant_leaks += sum(
            1
            for item in [*(row.get("evidence_locators") or []), *citations]
            if item.get("tenant_id") and item.get("tenant_id") != expected["tenant_id"]
        )

    total = len(cases)
    terminal_rate = valid_terminal / total
    degraded_mode = result_bundle["mode"] == "degraded"
    locator_precision = (
        correct_locator_count / predicted_locator_count
        if predicted_locator_count
        else 0.0
    )
    locator_recall = (
        correct_locator_count / expected_locator_count
        if expected_locator_count
        else 1.0
    )
    critical = {
        "hallucinations": hallucinations,
        "wrong_revision_citations": wrong_revision,
        "low_confidence_unreviewed": low_confidence_unreviewed,
        "unsafe_high_risk_answers": unsafe_high_risk_answers,
        "sop_conflict_misses": sop_conflict_misses,
        "cross_tenant_leaks": cross_tenant_leaks,
    }
    critical_error_count = sum(critical.values())
    checks = {
        "terminal_state_rate": terminal_rate >= thresholds.terminal_state_rate_min,
        # Degraded providers must abstain safely and explain terminal state. They
        # are not expected to emit evidence they could not extract.
        "evidence_locator_precision": degraded_mode
        or locator_precision >= thresholds.evidence_locator_precision_min,
        "evidence_locator_recall": degraded_mode
        or locator_recall >= thresholds.evidence_locator_recall_min,
        "critical_errors": critical_error_count <= thresholds.critical_error_max,
    }
    slices: dict[str, Any] = {}
    for key, counts in sorted(per_slice.items()):
        total_slice = counts["total"]
        predicted = counts["locator_predicted"]
        expected_count = counts["locator_expected"]
        slices[key] = {
            **dict(counts),
            "terminal_state_rate": counts["terminal_pass"] / total_slice,
            "locator_precision": (
                counts["locator_correct"] / predicted
                if predicted
                else (1.0 if expected_count == 0 else 0.0)
            ),
            "locator_recall": (
                counts["locator_correct"] / expected_count if expected_count else 1.0
            ),
        }
    checks["per_slice_terminal_state"] = all(
        item["terminal_state_rate"] >= thresholds.terminal_state_rate_min
        for item in slices.values()
    )
    checks["per_slice_evidence_locator"] = degraded_mode or all(
        item["locator_precision"] >= thresholds.evidence_locator_precision_min
        and item["locator_recall"] >= thresholds.evidence_locator_recall_min
        for item in slices.values()
    )

    return {
        "schema_version": 1,
        "gate": "P3-MULTIMODAL-QUALITY",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "evidence_class": (
            "contract_only"
            if result_bundle["mode"] == "mock_contract"
            else result_bundle["mode"]
        ),
        "provider": result_bundle["provider"],
        "provider_version": result_bundle["provider_version"],
        "mode": result_bundle["mode"],
        "corpus_sha256": corpus_sha256,
        "result_sha256": canonical_hash(result_bundle),
        "provenance": result_bundle.get("provenance") or {},
        "case_count": total,
        "terminal_state_rate": terminal_rate,
        "evidence_locator_precision": locator_precision,
        "evidence_locator_recall": locator_recall,
        "evidence_locator_applicable": not degraded_mode,
        "critical_errors": critical,
        "critical_error_count": critical_error_count,
        "checks": checks,
        "thresholds": thresholds.__dict__,
        "per_slice": slices,
    }


def build_contract_results(
    manifest: dict[str, Any], mode: str, provider: str, provider_version: str
) -> dict[str, Any]:
    """Build policy fixtures; never label these as live accuracy evidence."""
    cases = validate_manifest(manifest)
    if mode not in {"mock_contract", "degraded"}:
        raise CorpusValidationError(
            "synthetic result generation is limited to contract/degraded modes"
        )
    rows = []
    for case in cases:
        expected = case["expected"]
        degraded = mode == "degraded"
        terminal_state = "degraded" if degraded else expected["terminal_states"][0]
        answer_status = (
            "abstained" if expected.get("high_risk") or degraded else "not_applicable"
        )
        rows.append(
            {
                "case_id": case["id"],
                "terminal_state": terminal_state,
                "tenant_id": expected["tenant_id"],
                "evidence_locators": (
                    [] if degraded else deepcopy(expected.get("evidence_locators", []))
                ),
                "review_created": bool(
                    expected.get("low_confidence")
                    or expected.get("sop_conflict")
                    or degraded
                ),
                "sop_conflict_detected": bool(expected.get("sop_conflict"))
                and not degraded,
                "answer": {
                    "status": answer_status,
                    "grounded": True,
                    "authoritative": False,
                    "citations": [],
                },
            }
        )
    return {
        "schema_version": 1,
        "mode": mode,
        "provider": provider,
        "provider_version": provider_version,
        "corpus_sha256": canonical_hash(manifest),
        "results": rows,
    }


def aggregate_matrix(
    reports: Iterable[dict[str, Any]], required_modes: Iterable[str]
) -> dict[str, Any]:
    reports = list(reports)
    modes = [report.get("mode") for report in reports]
    duplicates = sorted({mode for mode in modes if modes.count(mode) > 1})
    by_mode = {report["mode"]: report for report in reports}
    missing = sorted(set(required_modes) - set(by_mode))
    failed = sorted(
        mode for mode, report in by_mode.items() if report.get("status") != "PASS"
    )
    return {
        "schema_version": 1,
        "gate": "P3-PROVIDER-MATRIX",
        "status": "PASS" if not missing and not failed and not duplicates else "FAIL",
        "required_modes": sorted(set(required_modes)),
        "missing_modes": missing,
        "failed_modes": failed,
        "duplicate_modes": duplicates,
        "reports": by_mode,
    }
