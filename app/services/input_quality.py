"""Input I4 quality gates for document, spreadsheet and image ingestion.

Parser completion is deliberately not treated as content correctness.  This
module owns the format-level thresholds used by the capability contract and by
the sealed-corpus replay.  It has no provider or domain-pack dependencies, so
the same evaluator can be used for native and external parser observations.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FormatQualityGate:
    key: str
    min_content_accuracy: float
    min_locator_coverage: float
    min_parse_success: float
    review_below_confidence: float
    sample_rate: float
    max_provider_regression: float = 0.03

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULT = FormatQualityGate(
    key="document-general-v1",
    min_content_accuracy=0.95,
    min_locator_coverage=0.95,
    min_parse_success=0.98,
    review_below_confidence=0.80,
    sample_rate=0.05,
)

FORMAT_QUALITY_GATES: dict[str, FormatQualityGate] = {
    ".txt": FormatQualityGate("text-exact-v1", 1.0, 1.0, 1.0, 0.80, 0.01),
    ".md": FormatQualityGate("markdown-structure-v1", 1.0, 1.0, 1.0, 0.80, 0.01),
    ".csv": FormatQualityGate("table-row-cell-v1", 1.0, 1.0, 1.0, 0.80, 0.02),
    ".xlsx": FormatQualityGate("xlsx-row-cell-v1", 1.0, 1.0, 1.0, 0.80, 0.03),
    ".docx": FormatQualityGate("docx-paragraph-v1", 1.0, 1.0, 1.0, 0.80, 0.03),
    ".pptx": FormatQualityGate("pptx-slide-v1", 1.0, 1.0, 1.0, 0.80, 0.03),
    ".pdf": FormatQualityGate("pdf-page-v1", 0.98, 1.0, 0.99, 0.90, 0.05),
    ".jpg": FormatQualityGate("image-ocr-region-v1", 0.92, 1.0, 0.98, 0.82, 0.10),
    ".jpeg": FormatQualityGate("image-ocr-region-v1", 0.92, 1.0, 0.98, 0.82, 0.10),
    ".png": FormatQualityGate("image-ocr-region-v1", 0.92, 1.0, 0.98, 0.82, 0.10),
    ".tif": FormatQualityGate("tiff-ocr-page-region-v1", 0.90, 1.0, 0.97, 0.82, 0.10),
    ".tiff": FormatQualityGate("tiff-ocr-page-region-v1", 0.90, 1.0, 0.97, 0.82, 0.10),
    ".heic": FormatQualityGate("heic-ocr-region-v1", 0.90, 1.0, 0.97, 0.82, 0.10),
}


def quality_gate_for(extension: str) -> FormatQualityGate:
    return FORMAT_QUALITY_GATES.get(extension.lower(), _DEFAULT)


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(ch for ch in value if ch.isalnum())


def _levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, 1):
        current = [index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def content_accuracy(expected: str, actual: str) -> float:
    """Character accuracy after conservative Unicode/spacing normalisation."""

    expected_value = _normalise(expected)
    actual_value = _normalise(actual)
    if not expected_value:
        return 1.0 if not actual_value else 0.0
    if expected_value in actual_value:
        return 1.0
    distance = _levenshtein(expected_value, actual_value)
    return max(0.0, 1.0 - distance / max(len(expected_value), len(actual_value), 1))


def evaluate_observations(
    extension: str, observations: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Evaluate a format without confusing successful calls with correctness."""

    rows = list(observations)
    gate = quality_gate_for(extension)
    if not rows:
        return {
            "extension": extension,
            "gate": gate.to_dict(),
            "status": "FAIL",
            "errors": ["no observations"],
        }
    parse_success = sum(bool(row.get("parse_success")) for row in rows) / len(rows)
    accuracies = [
        content_accuracy(str(row.get("expected") or ""), str(row.get("actual") or ""))
        for row in rows
        if row.get("parse_success")
    ]
    locator_flags = [
        bool(row.get("locator_complete"))
        for row in rows
        if row.get("parse_success")
    ]
    accuracy = sum(accuracies) / len(accuracies) if accuracies else 0.0
    locator_coverage = (
        sum(locator_flags) / len(locator_flags) if locator_flags else 0.0
    )
    failures = [
        {
            "id": str(row.get("id") or "unknown"),
            "parse_success": bool(row.get("parse_success")),
            "content_accuracy": (
                content_accuracy(
                    str(row.get("expected") or ""), str(row.get("actual") or "")
                )
                if row.get("parse_success")
                else 0.0
            ),
            "locator_complete": bool(row.get("locator_complete")),
            "reason": str(row.get("error") or "quality threshold miss"),
        }
        for row in rows
        if not row.get("parse_success")
        or content_accuracy(
            str(row.get("expected") or ""), str(row.get("actual") or "")
        )
        < gate.min_content_accuracy
        or not row.get("locator_complete")
    ]
    passed = (
        parse_success >= gate.min_parse_success
        and accuracy >= gate.min_content_accuracy
        and locator_coverage >= gate.min_locator_coverage
    )
    return {
        "extension": extension,
        "gate": gate.to_dict(),
        "status": "PASS" if passed else "FAIL",
        "sample_count": len(rows),
        "parse_success": round(parse_success, 6),
        "content_accuracy": round(accuracy, 6),
        "locator_coverage": round(locator_coverage, 6),
        "failures": failures,
    }


def provider_drift(
    extension: str, *, baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    gate = quality_gate_for(extension)
    metrics = ("parse_success", "content_accuracy", "locator_coverage")
    regressions = {
        metric: round(float(baseline.get(metric, 0)) - float(candidate.get(metric, 0)), 6)
        for metric in metrics
    }
    failed = {
        metric: value
        for metric, value in regressions.items()
        if value > gate.max_provider_regression
    }
    return {
        "extension": extension,
        "status": "FAIL" if failed else "PASS",
        "max_provider_regression": gate.max_provider_regression,
        "regressions": regressions,
        "failed_metrics": failed,
    }


def requires_human_review(
    extension: str,
    *,
    confidence: float | None,
    content_hash: str,
    fallback_used: bool = False,
    sampling_enabled: bool = True,
) -> bool:
    """Deterministic confidence routing plus stable audit sampling."""

    gate = quality_gate_for(extension)
    if fallback_used or confidence is None or confidence < gate.review_below_confidence:
        return True
    if not sampling_enabled:
        return False
    digest = hashlib.sha256(content_hash.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return bucket < gate.sample_rate


def terminology_hits(text: str, terminology: Iterable[str]) -> list[str]:
    """Return exact terms that survived extraction; never auto-correct evidence."""

    value = unicodedata.normalize("NFKC", text or "")
    hits = []
    for term in terminology:
        candidate = unicodedata.normalize("NFKC", str(term).strip())
        if candidate and re.search(re.escape(candidate), value, re.IGNORECASE):
            hits.append(str(term))
    return hits


# ---------------------------------------------------------------------------
# Input I10 generalisation contract

CLAIM_LEVELS = ("contract", "mechanical", "semantic", "journey")
_CLAIM_RANK = {value: index for index, value in enumerate(CLAIM_LEVELS)}
_EVIDENCE_CEILING = {
    "contract_only": "contract",
    "synthetic": "mechanical",
    "sealed_internal_synthetic": "mechanical",
    "raw_fixture": "mechanical",
    "historical_raw_fixture": "mechanical",
    "repository_generated_recipe": "mechanical",
    "licensed_internal": "semantic",
    "tenant_real": "semantic",
    "customer_real": "semantic",
}
_NO_CONTENT_OUTCOMES = {"not_applicable", "no_content", "no_speech", "no_text"}


@dataclass(frozen=True)
class GeneralizationQualityThresholds:
    """Thresholds for truth-backed, slice-aware Input certification.

    The defaults are intentionally unsuitable for declaring a corpus certified
    from one happy-path file.  Callers may version stricter modality-specific
    thresholds, but must not lower ``min_samples_per_slice`` implicitly.
    """

    max_cer: float = 0.15
    max_wer: float = 0.25
    min_locator_coverage: float = 1.0
    max_timestamp_p95_ms: float = 2_000.0
    min_samples_per_slice: int = 5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokenise_words(value: str) -> list[str]:
    """Tokenise Latin words/numbers and CJK characters without a segmenter."""

    normalised = unicodedata.normalize("NFKC", value or "").casefold()
    return re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", normalised)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return standard normalised edit distance for the complete text.

    Unlike :func:`content_accuracy`, this does not treat a reference substring
    as a perfect full-transcript match.  CER may exceed 1 when the parser adds
    substantial hallucinated text, which is useful evidence rather than noise.
    """

    expected = _normalise(reference)
    actual = _normalise(hypothesis)
    if not expected:
        return 0.0 if not actual else 1.0
    return _levenshtein(expected, actual) / len(expected)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Return token edit distance for mixed Traditional Chinese/Latin text."""

    expected = _tokenise_words(reference)
    actual = _tokenise_words(hypothesis)
    if not expected:
        return 0.0 if not actual else 1.0
    return _levenshtein(expected, actual) / len(expected)


def normalize_provider_confidence(
    value: float | None, *, provider_supplied: bool
) -> float | None:
    """Keep an unknown provider score distinct from a measured zero score."""

    if not provider_supplied or value is None:
        return None
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError("provider confidence must be between 0 and 1")
    return score


def evidence_claim_ceiling(
    evidence_class: str, *, ground_truth_verified: bool = False
) -> str:
    """Return the highest claim an evidence class is allowed to support.

    Real files without independently verified truth still prove only mechanical
    behaviour.  Parse evidence alone can never prove the end-to-end journey.
    """

    declared = _EVIDENCE_CEILING.get(str(evidence_class).strip().casefold(), "contract")
    if declared == "semantic" and not ground_truth_verified:
        return "mechanical"
    return declared


def assess_evidence_claim(
    *,
    evidence_class: str,
    execution_status: str,
    requested_claim: str,
    ground_truth_verified: bool = False,
    journey_verified: bool = False,
    declared_gaps: Iterable[str] = (),
) -> dict[str, Any]:
    """Prevent a local execution PASS from becoming an unsupported product claim."""

    if requested_claim not in CLAIM_LEVELS:
        raise ValueError(f"unknown requested claim: {requested_claim}")
    ceiling = evidence_claim_ceiling(
        evidence_class, ground_truth_verified=ground_truth_verified
    )
    if journey_verified and ceiling == "semantic":
        ceiling = "journey"
    gaps = [str(value) for value in declared_gaps if str(value).strip()]
    blockers: list[str] = []
    if execution_status != "PASS":
        blockers.append(f"execution status is {execution_status!r}, not 'PASS'")
        status = "FAIL"
    else:
        if _CLAIM_RANK[ceiling] < _CLAIM_RANK[requested_claim]:
            blockers.append(
                f"evidence ceiling {ceiling!r} cannot support {requested_claim!r}"
            )
        if requested_claim in {"semantic", "journey"} and gaps:
            blockers.append("declared coverage gaps remain open")
        status = "HOLD" if blockers else "PASS"
    return {
        "status": status,
        "execution_status": execution_status,
        "evidence_class": evidence_class,
        "claim_ceiling": ceiling,
        "requested_claim": requested_claim,
        "ground_truth_verified": ground_truth_verified,
        "journey_verified": journey_verified,
        "declared_gaps": gaps,
        "blocking_reasons": blockers,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _critical_fields(row: dict[str, Any]) -> tuple[int, int, list[dict[str, str]]]:
    fields = list(row.get("critical_fields") or [])
    misses: list[dict[str, str]] = []
    for field in fields:
        expected = str(field.get("expected") or "")
        actual = str(field.get("actual") or "")
        # Preserve decimal points, signs and separators.  The looser text
        # normaliser would make safety-critical values such as 6.5 and 65
        # indistinguishable.
        expected_value = re.sub(
            r"\s+", "", unicodedata.normalize("NFKC", expected).casefold()
        )
        actual_value = re.sub(
            r"\s+", "", unicodedata.normalize("NFKC", actual).casefold()
        )
        if expected_value != actual_value:
            misses.append(
                {
                    "name": str(field.get("name") or "unnamed"),
                    "expected": expected,
                    "actual": actual,
                }
            )
    return (len(fields) - len(misses), len(fields), misses)


def _timestamp_errors(row: dict[str, Any]) -> list[float]:
    errors: list[float] = []
    for pair in row.get("timestamp_pairs") or []:
        for boundary in ("start_ms", "end_ms"):
            expected = pair.get(f"expected_{boundary}")
            actual = pair.get(f"actual_{boundary}")
            if expected is not None and actual is not None:
                errors.append(abs(float(actual) - float(expected)))
    return errors


def evaluate_generalization_quality(
    observations: Iterable[dict[str, Any]],
    *,
    required_slices: Iterable[str],
    thresholds: GeneralizationQualityThresholds | None = None,
    requested_claim: str = "semantic",
) -> dict[str, Any]:
    """Evaluate Input quality without letting averages or synthetic data overclaim.

    Every required slice is judged independently.  A single measured quality
    failure fails that slice even when the global average looks healthy.  A
    missing/undersized/insufficient-evidence slice produces ``HOLD`` rather than
    a false PASS.  ``journey`` is deliberately unavailable here because it must
    be proven by publish -> Ask -> citation -> revocation evidence.
    """

    if requested_claim not in CLAIM_LEVELS:
        raise ValueError(f"unknown requested claim: {requested_claim}")
    if requested_claim == "journey":
        raise ValueError("journey claims require an end-to-end journey evaluator")

    gate = thresholds or GeneralizationQualityThresholds()
    rows = [dict(row) for row in observations]
    required = list(dict.fromkeys(str(value) for value in required_slices))
    grouped: dict[str, list[dict[str, Any]]] = {value: [] for value in required}
    for row in rows:
        slice_name = str(row.get("slice") or "unspecified")
        grouped.setdefault(slice_name, []).append(row)

    slice_reports: dict[str, dict[str, Any]] = {}
    for slice_name in required:
        slice_rows = grouped.get(slice_name, [])
        if not slice_rows:
            slice_reports[slice_name] = {
                "status": "HOLD",
                "sample_count": 0,
                "claim_ceiling": "contract",
                "blocking_reasons": ["required slice has no observations"],
            }
            continue

        case_reports: list[dict[str, Any]] = []
        semantic_eligible = 0
        semantic_passes = 0
        locator_successes = 0
        critical_successes = 0
        critical_total = 0
        timestamp_errors: list[float] = []
        evidence_ceilings: list[str] = []
        measured_failures: list[str] = []

        for index, row in enumerate(slice_rows):
            case_id = str(row.get("id") or f"{slice_name}:{index + 1}")
            outcome = str(row.get("capability_outcome") or "available")
            expected_outcome = str(row.get("expected_outcome") or "available")
            truth_verified = bool(row.get("ground_truth_verified"))
            ceiling = evidence_claim_ceiling(
                str(row.get("evidence_class") or "contract_only"),
                ground_truth_verified=truth_verified,
            )
            evidence_ceilings.append(ceiling)
            outcome_matches = outcome == expected_outcome
            is_no_content = expected_outcome in _NO_CONTENT_OUTCOMES
            parse_success = bool(row.get("parse_success")) or (
                is_no_content and outcome_matches
            )
            locator_complete = bool(row.get("locator_complete")) or is_no_content
            locator_successes += int(locator_complete)

            reference = row.get("reference")
            hypothesis = row.get("hypothesis")
            cer = None
            wer = None
            fields_ok, fields_total, field_misses = _critical_fields(row)
            critical_successes += fields_ok
            critical_total += fields_total
            boundary_errors = _timestamp_errors(row)
            timestamp_errors.extend(boundary_errors)
            timestamp_required = bool(row.get("timestamp_required"))
            timestamp_p95 = _percentile(boundary_errors, 0.95)

            semantic_case = (
                truth_verified
                and _CLAIM_RANK[ceiling] >= _CLAIM_RANK["semantic"]
                and outcome_matches
            )
            if semantic_case:
                semantic_eligible += 1
                if not is_no_content:
                    if reference is not None and hypothesis is not None:
                        cer = character_error_rate(str(reference), str(hypothesis))
                        wer = word_error_rate(str(reference), str(hypothesis))

            semantic_requirements_pass = requested_claim != "semantic" or (
                semantic_case
                and (
                    is_no_content
                    or (
                        cer is not None
                        and wer is not None
                        and cer <= gate.max_cer
                        and wer <= gate.max_wer
                    )
                )
            )
            case_pass = (
                parse_success
                and outcome_matches
                and locator_complete
                and not field_misses
                and (not timestamp_required or timestamp_p95 is not None)
                and (timestamp_p95 is None or timestamp_p95 <= gate.max_timestamp_p95_ms)
                and semantic_requirements_pass
            )
            if semantic_case and case_pass:
                semantic_passes += 1

            failures: list[str] = []
            if not parse_success:
                failures.append("processor did not produce a valid capability outcome")
            if not outcome_matches:
                failures.append(
                    f"capability outcome {outcome!r} != expected {expected_outcome!r}"
                )
            if not locator_complete:
                failures.append("evidence locator is incomplete")
            if field_misses:
                failures.append("critical field mismatch")
            if timestamp_required and timestamp_p95 is None:
                failures.append("required timestamp ground truth is missing")
            elif timestamp_p95 is not None and timestamp_p95 > gate.max_timestamp_p95_ms:
                failures.append("timestamp P95 exceeds threshold")
            if requested_claim == "semantic" and semantic_case and not is_no_content:
                if cer is None or wer is None:
                    failures.append("verified text ground truth is missing")
                elif cer > gate.max_cer or wer > gate.max_wer:
                    failures.append("semantic text error exceeds threshold")
            mechanical_failure = (
                not parse_success
                or not outcome_matches
                or not locator_complete
                or bool(field_misses)
                or (timestamp_required and timestamp_p95 is None)
                or (
                    timestamp_p95 is not None
                    and timestamp_p95 > gate.max_timestamp_p95_ms
                )
            )
            semantic_failure = (
                requested_claim == "semantic" and semantic_case and not case_pass
            )
            if mechanical_failure or semantic_failure:
                measured_failures.append(case_id)
            case_status = (
                "PASS"
                if case_pass
                else "FAIL"
                if mechanical_failure or semantic_failure
                else "HOLD"
            )

            case_reports.append(
                {
                    "id": case_id,
                    "evidence_class": str(
                        row.get("evidence_class") or "contract_only"
                    ),
                    "claim_ceiling": ceiling,
                    "ground_truth_verified": truth_verified,
                    "capability_outcome": outcome,
                    "expected_outcome": expected_outcome,
                    "cer": round(cer, 6) if cer is not None else None,
                    "wer": round(wer, 6) if wer is not None else None,
                    "locator_complete": locator_complete,
                    "critical_field_misses": field_misses,
                    "timestamp_p95_ms": timestamp_p95,
                    "status": case_status,
                    "failures": failures,
                }
            )

        locator_coverage = locator_successes / len(slice_rows)
        semantic_ci = _wilson_interval(semantic_passes, semantic_eligible)
        evidence_ceiling = min(
            evidence_ceilings, key=lambda value: _CLAIM_RANK[value]
        )
        blockers: list[str] = []
        if len(slice_rows) < gate.min_samples_per_slice:
            blockers.append(
                f"sample_count={len(slice_rows)} below min_samples_per_slice="
                f"{gate.min_samples_per_slice}"
            )
        if _CLAIM_RANK[evidence_ceiling] < _CLAIM_RANK[requested_claim]:
            blockers.append(
                f"evidence ceiling {evidence_ceiling!r} cannot support "
                f"{requested_claim!r}"
            )
        if requested_claim == "semantic" and semantic_eligible < gate.min_samples_per_slice:
            blockers.append(
                f"truth-backed semantic samples={semantic_eligible} below required "
                f"{gate.min_samples_per_slice}"
            )
        if locator_coverage < gate.min_locator_coverage:
            measured_failures.append("locator_coverage")

        status = "FAIL" if measured_failures else ("HOLD" if blockers else "PASS")
        slice_reports[slice_name] = {
            "status": status,
            "sample_count": len(slice_rows),
            "semantic_sample_count": semantic_eligible,
            "semantic_pass_count": semantic_passes,
            "semantic_pass_rate": round(
                semantic_passes / semantic_eligible, 6
            )
            if semantic_eligible
            else None,
            "semantic_pass_rate_wilson_95": [round(value, 6) for value in semantic_ci],
            "locator_coverage": round(locator_coverage, 6),
            "critical_field_exact": {
                "successes": critical_successes,
                "total": critical_total,
                "rate": round(critical_successes / critical_total, 6)
                if critical_total
                else None,
            },
            "timestamp_p95_ms": _percentile(timestamp_errors, 0.95),
            "claim_ceiling": evidence_ceiling,
            "blocking_reasons": blockers,
            "measured_failures": sorted(set(measured_failures)),
            "cases": case_reports,
        }

    required_reports = [slice_reports[value] for value in required]
    if any(row["status"] == "FAIL" for row in required_reports):
        status = "FAIL"
    elif any(row["status"] == "HOLD" for row in required_reports):
        status = "HOLD"
    else:
        status = "PASS"
    overall_ceiling = (
        min(
            (row["claim_ceiling"] for row in required_reports),
            key=lambda value: _CLAIM_RANK[value],
        )
        if required_reports
        else "contract"
    )
    return {
        "schema_version": "input-generalization-quality.v1",
        "status": status,
        "requested_claim": requested_claim,
        "claim_ceiling": overall_ceiling,
        "thresholds": gate.to_dict(),
        "required_slices": required,
        "observed_sample_count": len(rows),
        "slices": slice_reports,
        "statement": (
            "PASS certifies only the requested claim and listed slices; it never "
            "implies an end-to-end product journey certification."
        ),
    }
