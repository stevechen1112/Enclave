from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.platform.intake.capabilities import DOCUMENT_FORMAT_SPECS

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "input" / "i4_quality_corpus_manifest.json"
BASELINE = ROOT / "artifacts" / "input" / "i4_quality_baseline.json"
REPORT = ROOT / "artifacts" / "input" / "i4_quality_report.json"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_i4_corpus_is_sealed_and_contains_no_customer_claim():
    manifest = _read(MANIFEST)
    entries = manifest["entries"]
    encoded = json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert manifest["status"] == "SEALED_INTERNAL_SYNTHETIC"
    assert hashlib.sha256(encoded).hexdigest() == manifest["corpus_sha256"]
    assert "not customer" in manifest["purpose"].lower()
    for entry in entries:
        path = ROOT / entry["path"]
        payload = path.read_bytes()
        assert len(payload) == entry["bytes"]
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]


def test_every_open_document_ui_format_has_passed_quality_and_failure_sample():
    report = _read(REPORT)
    assert report["status"] == "PASS"
    assert report["certification"]["status"] == "HOLD"
    assert report["certification"]["claim_ceiling"] == "mechanical"
    opened = {
        spec.extension
        for spec in DOCUMENT_FORMAT_SPECS
        if spec.ui_default and spec.evidence_state == "internally_verified"
    }
    assert opened <= set(report["formats"]), opened - set(report["formats"])
    for extension in opened:
        assert report["formats"][extension]["status"] == "PASS"
        assert report["formats"][extension]["content_accuracy"] >= report["formats"][extension]["gate"]["min_content_accuracy"]
        assert report["formats"][extension]["locator_coverage"] >= report["formats"][extension]["gate"]["min_locator_coverage"]
        assert report["failure_samples"][extension]["status"] == "FAIL"


def test_i4_provider_drift_replay_and_baseline_are_bound_to_same_corpus():
    baseline = _read(BASELINE)
    report = _read(REPORT)
    assert baseline["corpus_sha256"] == report["corpus_sha256"]
    assert set(report["provider_drift"]) == set(report["formats"])
    assert all(row["status"] == "PASS" for row in report["provider_drift"].values())


def test_i4_opens_pptx_and_tiff_but_keeps_uncertified_legacy_and_heic_closed():
    by_extension = {spec.extension: spec for spec in DOCUMENT_FORMAT_SPECS}
    assert by_extension[".pptx"].ui_default is True
    assert by_extension[".tiff"].ui_default is True
    for extension in (".doc", ".xls", ".heic"):
        assert by_extension[extension].ui_default is False
        assert by_extension[extension].evidence_state != "internally_verified"


def test_i4_report_preserves_formula_hidden_sheet_rotation_and_multipage_policy():
    cases = {row["id"]: row for row in _read(REPORT)["cases"]}
    assert cases["bom-xlsx"]["structure_policy"]["formula_policy"] == "preserve_formula_expression"
    assert cases["bom-xlsx"]["structure_policy"]["hidden_sheets"] == ["成本_機密"]
    assert any("rotate_" in value for value in cases["rotated-label-png"]["structure_policy"]["preprocessing"])
    assert cases["multipage-tiff"]["structure_policy"]["multi_page_policy"] == "preserve_frame_as_page"
