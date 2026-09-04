"""Replayable audio/video accuracy metrics with strict truth provenance.

This module deliberately refuses to turn contract fixtures into accuracy
evidence.  It contains no model calls and can therefore be used for regression,
sealed holdout and tenant-acceptance runs without changing their truth data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from statistics import median
from typing import Any


class MediaTruthError(ValueError):
    """The corpus/result pair cannot be used as trustworthy evidence."""


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tokens(text: str, unit: str) -> list[str]:
    normalized = " ".join(str(text or "").strip().lower().split())
    return (
        list(normalized.replace(" ", "")) if unit == "character" else normalized.split()
    )


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, ref in enumerate(reference, 1):
        current = [row]
        for column, hyp in enumerate(hypothesis, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref != hyp),
                )
            )
        previous = current
    return previous[-1]


def error_rate(reference: str, hypothesis: str, *, unit: str) -> float:
    reference_tokens = _tokens(reference, unit)
    hypothesis_tokens = _tokens(hypothesis, unit)
    if not reference_tokens:
        return 0.0 if not hypothesis_tokens else 1.0
    return edit_distance(reference_tokens, hypothesis_tokens) / len(reference_tokens)


def _interval_iou(expected: dict[str, Any], predicted: dict[str, Any]) -> float:
    start = max(int(expected["start_ms"]), int(predicted["start_ms"]))
    end = min(int(expected["end_ms"]), int(predicted["end_ms"]))
    overlap = max(0, end - start)
    union = max(int(expected["end_ms"]), int(predicted["end_ms"])) - min(
        int(expected["start_ms"]), int(predicted["start_ms"])
    )
    return overlap / union if union else 0.0


def _match_events(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> int:
    remaining = list(predicted)
    matches = 0
    for event in expected:
        candidates = [
            (index, row)
            for index, row in enumerate(remaining)
            if row.get("label") == event.get("label")
            and _interval_iou(event, row) >= 0.5
        ]
        if candidates:
            best = max(candidates, key=lambda item: _interval_iou(event, item[1]))
            remaining.pop(best[0])
            matches += 1
    return matches


def _bbox_iou(expected: list[float], predicted: list[float]) -> float:
    if len(expected) != 4 or len(predicted) != 4:
        return 0.0
    ex1, ey1, ex2, ey2 = map(float, expected)
    px1, py1, px2, py2 = map(float, predicted)
    intersection = max(0.0, min(ex2, px2) - max(ex1, px1)) * max(
        0.0, min(ey2, py2) - max(ey1, py1)
    )
    expected_area = max(0.0, ex2 - ex1) * max(0.0, ey2 - ey1)
    predicted_area = max(0.0, px2 - px1) * max(0.0, py2 - py1)
    union = expected_area + predicted_area - intersection
    return intersection / union if union else 0.0


def _repetition_candidates(text: str) -> list[str]:
    tokens = _tokens(text, "word")
    repeated: set[str] = set()
    for width in (1, 2, 3):
        for index in range(max(0, len(tokens) - width * 3 + 1)):
            phrase = tokens[index : index + width]
            if (
                phrase
                == tokens[index + width : index + width * 2]
                == tokens[index + width * 2 : index + width * 3]
            ):
                repeated.add(" ".join(phrase))
    return sorted(repeated)


@dataclass(frozen=True)
class MediaThresholds:
    clear_audio_cer_max: float = 0.12
    difficult_audio_cer_max: float = 0.25
    critical_term_recall_min: float = 0.95
    clear_ocr_cer_max: float = 0.10
    difficult_ocr_cer_max: float = 0.25
    critical_event_recall_min: float = 0.95
    entity_precision_min: float = 0.98
    unsupported_high_risk_max: int = 0
    cross_tenant_leak_max: int = 0


def validate_truth_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != 2:
        raise MediaTruthError("manifest.schema_version must be 2")
    classification = manifest.get("classification")
    if classification not in {
        "development_regression",
        "sealed_holdout",
        "tenant_acceptance",
        "production_shadow",
    }:
        raise MediaTruthError("invalid corpus classification")
    provenance = manifest.get("provenance") or {}
    required = {"owner", "created_at", "content_license", "corpus_id"}
    if not required <= set(provenance):
        raise MediaTruthError("corpus provenance is incomplete")
    if classification == "sealed_holdout" and not provenance.get("sealed_at"):
        raise MediaTruthError("sealed holdout requires sealed_at")
    if classification == "tenant_acceptance" and not provenance.get("truth_owner"):
        raise MediaTruthError("tenant acceptance requires truth_owner")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise MediaTruthError("manifest.cases must be non-empty")
    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            raise MediaTruthError("case ids must be present and unique")
        seen.add(case_id)
        if case.get("modality") not in {"audio", "video"}:
            raise MediaTruthError(f"{case_id}: modality must be audio or video")
        if not case.get("slice") or not case.get("tenant_id"):
            raise MediaTruthError(f"{case_id}: slice and tenant_id are required")
        truth = case.get("truth") or {}
        if case["modality"] == "audio" and "transcript" not in truth:
            raise MediaTruthError(f"{case_id}: audio transcript truth is required")
        if case["modality"] == "video" and not any(
            key in truth for key in ("transcript", "ocr_text", "events")
        ):
            raise MediaTruthError(f"{case_id}: video truth is empty")
    return cases


def evaluate_media_quality(
    manifest: dict[str, Any],
    result_bundle: dict[str, Any],
    thresholds: MediaThresholds | None = None,
) -> dict[str, Any]:
    cases = validate_truth_manifest(manifest)
    if result_bundle.get("corpus_sha256") != _hash(manifest):
        raise MediaTruthError("results are not bound to this corpus")
    provenance = result_bundle.get("provenance") or {}
    if not {"run_id", "captured_at", "source_commit", "runtime_manifest_hash"} <= set(
        provenance
    ):
        raise MediaTruthError("result provenance is incomplete")
    rows = result_bundle.get("results")
    if not isinstance(rows, list):
        raise MediaTruthError("results must be a list")
    by_id = {str(row.get("case_id")): row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {case["id"] for case in cases}:
        raise MediaTruthError("result case set must exactly match corpus")
    thresholds = thresholds or MediaThresholds()
    slice_rows: dict[str, list[dict[str, Any]]] = {}
    critical_expected = critical_found = 0
    event_expected = event_found = 0
    entity_tp = entity_fp = 0
    unsupported_high_risk = cross_tenant_leaks = 0
    forbidden_insertions = 0
    speaker_expected = speaker_found = 0
    retrieval_expected = retrieval_found = 0
    reciprocal_ranks: list[float] = []
    bbox_scores: list[float] = []
    repetition_candidates: dict[str, list[str]] = {}
    all_case_metrics: list[dict[str, Any]] = []
    for case in cases:
        row = by_id[case["id"]]
        if row.get("tenant_id") != case["tenant_id"]:
            cross_tenant_leaks += 1
        truth, predicted = case["truth"], row.get("predicted") or {}
        metrics: dict[str, Any] = {"case_id": case["id"], "slice": case["slice"]}
        if "transcript" in truth:
            metrics["cer"] = error_rate(
                truth["transcript"], predicted.get("transcript", ""), unit="character"
            )
            metrics["wer"] = error_rate(
                truth["transcript"], predicted.get("transcript", ""), unit="word"
            )
        if "ocr_text" in truth:
            metrics["ocr_cer"] = error_rate(
                truth["ocr_text"], predicted.get("ocr_text", ""), unit="character"
            )
        truth_terms = {str(item).lower() for item in truth.get("critical_terms", [])}
        predicted_text = " ".join(
            str(predicted.get(key) or "")
            for key in ("transcript", "ocr_text", "summary")
        ).lower()
        critical_expected += len(truth_terms)
        found = sum(term in predicted_text for term in truth_terms)
        critical_found += found
        metrics["critical_terms_expected"] = len(truth_terms)
        metrics["critical_terms_found"] = found
        expected_events, predicted_events = truth.get("events", []), predicted.get(
            "events", []
        )
        matches = _match_events(expected_events, predicted_events)
        event_expected += len(expected_events)
        event_found += matches
        metrics["event_expected"] = len(expected_events)
        metrics["event_found"] = matches
        expected_entities = set(truth.get("entity_ids", []))
        predicted_entities = set(predicted.get("entity_ids", []))
        entity_tp += len(expected_entities & predicted_entities)
        entity_fp += len(predicted_entities - expected_entities)
        forbidden = {str(item).lower() for item in truth.get("forbidden_terms", [])}
        inserted = sorted(term for term in forbidden if term in predicted_text)
        forbidden_insertions += len(inserted)
        metrics["forbidden_insertions"] = inserted

        expected_turns = truth.get("speaker_turns", [])
        predicted_turns = predicted.get("speaker_turns", [])
        speaker_matches = _match_events(
            [dict(turn, label=turn.get("speaker")) for turn in expected_turns],
            [dict(turn, label=turn.get("speaker")) for turn in predicted_turns],
        )
        speaker_expected += len(expected_turns)
        speaker_found += speaker_matches
        metrics["speaker_turn_expected"] = len(expected_turns)
        metrics["speaker_turn_found"] = speaker_matches

        expected_units = [str(value) for value in truth.get("retrieval_unit_ids", [])]
        retrieved_units = [
            str(value) for value in predicted.get("retrieval_unit_ids", [])
        ]
        found_units = len(set(expected_units) & set(retrieved_units))
        retrieval_expected += len(expected_units)
        retrieval_found += found_units
        ranks = [
            retrieved_units.index(value) + 1
            for value in expected_units
            if value in retrieved_units
        ]
        if expected_units:
            reciprocal_ranks.append(1.0 / min(ranks) if ranks else 0.0)
        metrics["retrieval_expected"] = len(expected_units)
        metrics["retrieval_found"] = found_units

        predicted_regions = predicted.get("ocr_regions", [])
        for expected_region in truth.get("ocr_regions", []):
            matching = [
                region
                for region in predicted_regions
                if str(region.get("text") or "").strip().lower()
                == str(expected_region.get("text") or "").strip().lower()
            ]
            bbox_scores.append(
                max(
                    (
                        _bbox_iou(
                            expected_region.get("bbox", []), candidate.get("bbox", [])
                        )
                        for candidate in matching
                    ),
                    default=0.0,
                )
            )
        repetitions = _repetition_candidates(predicted.get("transcript", ""))
        if repetitions:
            repetition_candidates[case["id"]] = repetitions
        if (
            case.get("high_risk")
            and row.get("answer_status") == "answered"
            and not row.get("evidence_complete")
        ):
            unsupported_high_risk += 1
        slice_rows.setdefault(case["slice"], []).append(metrics)
        all_case_metrics.append(metrics)

    def average(key: str, items: list[dict[str, Any]]) -> float | None:
        values = [float(item[key]) for item in items if key in item]
        return sum(values) / len(values) if values else None

    def median_value(key: str, items: list[dict[str, Any]]) -> float | None:
        values = [float(item[key]) for item in items if key in item]
        return median(values) if values else None

    per_slice = {
        key: {
            "case_count": len(items),
            "mean_cer": average("cer", items),
            "median_cer": median_value("cer", items),
            "mean_wer": average("wer", items),
            "mean_ocr_cer": average("ocr_cer", items),
            "median_ocr_cer": median_value("ocr_cer", items),
        }
        for key, items in sorted(slice_rows.items())
    }
    critical_recall = critical_found / critical_expected if critical_expected else 1.0
    event_recall = event_found / event_expected if event_expected else 1.0
    entity_precision = (
        entity_tp / (entity_tp + entity_fp) if entity_tp + entity_fp else 1.0
    )
    speaker_turn_recall = speaker_found / speaker_expected if speaker_expected else 1.0
    retrieval_recall = (
        retrieval_found / retrieval_expected if retrieval_expected else 1.0
    )
    checks = {
        "critical_term_recall": critical_recall >= thresholds.critical_term_recall_min,
        "critical_event_recall": event_recall >= thresholds.critical_event_recall_min,
        "entity_precision": entity_precision >= thresholds.entity_precision_min,
        "unsupported_high_risk": unsupported_high_risk
        <= thresholds.unsupported_high_risk_max,
        "cross_tenant_leak": cross_tenant_leaks <= thresholds.cross_tenant_leak_max,
        "forbidden_term_insertion": forbidden_insertions == 0,
    }
    for slice_name, metrics in per_slice.items():
        difficult = any(
            token in slice_name
            for token in ("noisy", "far_field", "low_light", "motion_blur", "difficult")
        )
        if metrics["median_cer"] is not None:
            checks[f"audio_cer:{slice_name}"] = metrics["median_cer"] <= (
                thresholds.difficult_audio_cer_max
                if difficult
                else thresholds.clear_audio_cer_max
            )
        if metrics["median_ocr_cer"] is not None:
            checks[f"ocr_cer:{slice_name}"] = metrics["median_ocr_cer"] <= (
                thresholds.difficult_ocr_cer_max
                if difficult
                else thresholds.clear_ocr_cer_max
            )
    return {
        "schema_version": 2,
        "gate": "AV0-MEDIA-TRUTH",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "evidence_class": manifest["classification"],
        "corpus_sha256": _hash(manifest),
        "result_sha256": _hash(result_bundle),
        "case_count": len(cases),
        "critical_term_recall": critical_recall,
        "critical_event_recall": event_recall,
        "entity_precision": entity_precision,
        "speaker_turn_recall_at_iou_0_5": speaker_turn_recall,
        "retrieval_recall": retrieval_recall,
        "retrieval_mrr": (
            sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 1.0
        ),
        "mean_ocr_bbox_iou": (
            sum(bbox_scores) / len(bbox_scores) if bbox_scores else None
        ),
        "forbidden_term_insertions": forbidden_insertions,
        "unsupported_high_risk": unsupported_high_risk,
        "cross_tenant_leaks": cross_tenant_leaks,
        "repetition_candidates": repetition_candidates,
        "checks": checks,
        "per_slice": per_slice,
        "cases": all_case_metrics,
        "thresholds": thresholds.__dict__,
        "provenance": provenance,
    }


def corpus_sha256(manifest: dict[str, Any]) -> str:
    return _hash(manifest)
