"""Input I5 media quality and evidence-alignment evaluation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class TimelineObservation:
    expected_start_ms: int
    actual_start_ms: int
    expected_end_ms: int | None = None
    actual_end_ms: int | None = None


def evaluate_timeline_alignment(
    observations: list[TimelineObservation], *, maximum_mean_error_ms: int = 1_000
) -> dict[str, Any]:
    if not observations:
        return {
            "status": "FAIL",
            "reason": "no_ground_truth_observations",
            "sample_count": 0,
            "mean_absolute_error_ms": None,
            "max_absolute_error_ms": None,
        }
    errors: list[int] = []
    for row in observations:
        errors.append(abs(row.actual_start_ms - row.expected_start_ms))
        if row.expected_end_ms is not None and row.actual_end_ms is not None:
            errors.append(abs(row.actual_end_ms - row.expected_end_ms))
    mean_error = round(mean(errors), 2)
    return {
        "status": "PASS" if mean_error <= maximum_mean_error_ms else "FAIL",
        "sample_count": len(observations),
        "boundary_count": len(errors),
        "mean_absolute_error_ms": mean_error,
        "max_absolute_error_ms": max(errors),
        "threshold_ms": maximum_mean_error_ms,
    }


def evaluate_media_matrix(
    rows: list[dict[str, Any]], *, required_extensions: set[str]
) -> dict[str, Any]:
    by_extension = {str(row.get("extension") or "").lower(): row for row in rows}
    missing = sorted(required_extensions - set(by_extension))
    failed = sorted(
        extension
        for extension, row in by_extension.items()
        if extension in required_extensions and row.get("status") != "PASS"
    )
    return {
        "status": "PASS" if not missing and not failed else "FAIL",
        "required_extensions": sorted(required_extensions),
        "missing_extensions": missing,
        "failed_extensions": failed,
        "rows": rows,
    }


def candidate_publication_allowed(
    *, confidence: float | None, has_unresolved_conflict: bool, reviewed: bool
) -> bool:
    """Fail closed: model candidates never self-publish."""

    return bool(
        reviewed
        and not has_unresolved_conflict
        and confidence is not None
        and confidence >= 0.75
    )
