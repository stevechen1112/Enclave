"""Input I4 quality gates for document, spreadsheet and image ingestion.

Parser completion is deliberately not treated as content correctness.  This
module owns the format-level thresholds used by the capability contract and by
the sealed-corpus replay.  It has no provider or domain-pack dependencies, so
the same evaluator can be used for native and external parser observations.
"""

from __future__ import annotations

import hashlib
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
