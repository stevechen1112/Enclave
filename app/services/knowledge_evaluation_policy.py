"""KQ7 deterministic evaluation invariants and staged quality policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

PIPELINE_STAGES = (
    "parse",
    "retrieve",
    "select",
    "applicability",
    "completeness",
    "conversation",
)
RELEASE_THRESHOLDS = {
    "internal_alpha": {"strict": 0.85, "domain": 0.80},
    "external_beta": {"strict": 0.90, "domain": 0.85},
    "ga": {"strict": 0.95, "domain": 0.90},
}
CLASSIFICATION_METRICS = (
    "false_acceptance",
    "false_rejection",
    "partial_correctness",
    "conflict_correctness",
)
_EXECUTION_FAILURES = {
    "provider_error",
    "schema_error",
    "timeout",
    "pack_failure",
    "internal_error",
}


def stage_trace_errors(trace: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    rows = list(trace)
    stages = tuple(str(row.get("stage") or "") for row in rows)
    errors: list[str] = []
    if stages != PIPELINE_STAGES:
        errors.append("pipeline_stage_order_or_membership_invalid")
    for stage, row in zip(PIPELINE_STAGES, rows):
        if not str(row.get("status") or "").strip():
            errors.append(f"pipeline_stage_status_missing:{stage}")
    return tuple(errors)


def classification_quality(
    results: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    counts = {
        name: {"numerator": 0, "denominator": 0} for name in CLASSIFICATION_METRICS
    }
    for item in results:
        metrics = dict(item.get("metrics") or {})
        if str(metrics.get("execution_status") or "ok") in _EXECUTION_FAILURES:
            continue
        expected = str(metrics.get("expected_class") or "")
        actual = str(metrics.get("actual_class") or "")
        if expected in {"absent", "insufficient_context", "abstain", "clarify"}:
            counts["false_acceptance"]["denominator"] += 1
            counts["false_acceptance"]["numerator"] += int(
                actual in {"answer", "complete"}
            )
        if expected in {"answer", "complete"}:
            counts["false_rejection"]["denominator"] += 1
            counts["false_rejection"]["numerator"] += int(
                actual not in {"answer", "complete"}
            )
        if expected == "partial":
            counts["partial_correctness"]["denominator"] += 1
            counts["partial_correctness"]["numerator"] += int(actual == "partial")
        if expected == "conflict":
            counts["conflict_correctness"]["denominator"] += 1
            counts["conflict_correctness"]["numerator"] += int(actual == "conflict")
    for name, row in counts.items():
        denominator = row["denominator"]
        row["rate"] = row["numerator"] / denominator if denominator else None
        row["kind"] = "error_rate" if name.startswith("false_") else "correctness_rate"
    return counts


def release_threshold_errors(summary: Mapping[str, Any], stage: str) -> tuple[str, ...]:
    if stage not in RELEASE_THRESHOLDS:
        return ("release_stage_unknown",)
    threshold = RELEASE_THRESHOLDS[stage]
    errors: list[str] = []
    total = int(summary.get("total") or 0)
    if total < 200:
        errors.append("case_count_below_200")
    domain_distribution = dict(summary.get("domain_distribution") or {})
    if len(domain_distribution) < 4:
        errors.append("fewer_than_four_domains")
    errors.extend(
        f"domain_case_count_below_50:{domain}"
        for domain, count in domain_distribution.items()
        if int(count or 0) < 50
    )
    language_profiles = dict(summary.get("language_profile_distribution") or {})
    mixed = sum(
        int(language_profiles.get(key) or 0)
        for key in ("mixed", "abbreviation", "code", "cross_language")
    )
    if total and mixed / total < 0.20:
        errors.append("mixed_language_cases_below_20_percent")
    if (
        float((summary.get("strict_assertions") or {}).get("rate") or 0)
        < threshold["strict"]
    ):
        errors.append(f"strict_pass_below_{int(threshold['strict'] * 100)}_percent")
    if int(summary.get("critical_errors") or 0):
        errors.append("critical_error_present")
    for domain, quality in (summary.get("domain_quality") or {}).items():
        if int(quality.get("denominator") or 0) < 50:
            errors.append(f"domain_strict_denominator_below_50:{domain}")
        elif float(quality.get("rate") or 0) < threshold["domain"]:
            errors.append(
                f"domain_below_{int(threshold['domain'] * 100)}_percent:{domain}"
            )
    slots = dict(summary.get("required_slot_coverage") or {})
    if not slots.get("denominator") or float(slots.get("rate") or 0) < 0.95:
        errors.append("required_slot_coverage_below_95_percent_or_unmeasured")
    if int(summary.get("pipeline_invariant_violations") or 0):
        errors.append("pipeline_invariant_violation_present")
    for metric in CLASSIFICATION_METRICS:
        if metric not in (summary.get("classification_quality") or {}):
            errors.append(f"classification_metric_missing:{metric}")
    return tuple(errors)


def validate_regression_manifest(
    entries: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    errors: list[str] = []
    for index, entry in enumerate(entries):
        if str(entry.get("disclosure_status") or "") not in {"disclosed", "neighbor"}:
            errors.append(f"regression_disclosure_missing:{index}")
        if not str(entry.get("source_reference") or "").strip():
            errors.append(f"regression_source_missing:{index}")
        if str(entry.get("split") or "") == "sealed":
            errors.append(f"disclosed_case_mislabeled_sealed:{index}")
    return tuple(errors)


def holdout_pair_errors(runs: Iterable[Any]) -> tuple[str, ...]:
    selected = list(runs)
    errors: list[str] = []
    if len(selected) != 2:
        return ("exactly_two_holdouts_required",)
    if len({run.corpus_hash for run in selected}) != 2:
        errors.append("holdout_corpora_overlap")
    if len({run.question_hash for run in selected}) != 2:
        errors.append("holdout_questions_overlap")
    for index, run in enumerate(selected):
        runtime = dict(run.runtime_manifest or {})
        seal = dict(runtime.get("holdout_seal") or {})
        if seal.get("corpus_manifest_sha256") != run.corpus_hash:
            errors.append(f"holdout_corpus_not_sealed:{index}")
        if seal.get("questions_sha256") != run.question_hash:
            errors.append(f"holdout_questions_not_sealed:{index}")
        if len(str(seal.get("attestation_sha256") or "")) != 64:
            errors.append(f"holdout_independent_attestation_missing:{index}")
        if (
            str(seal.get("custodian") or "").strip().casefold()
            == str(runtime.get("implementer") or "").strip().casefold()
        ):
            errors.append(f"holdout_custodian_not_independent:{index}")
        if not bool(getattr(run, "first_run", False)):
            errors.append(f"holdout_not_first_run:{index}")
    return tuple(errors)
