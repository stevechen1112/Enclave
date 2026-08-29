from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.services.input_corpus_manifest import verify_input_corpus_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "input" / "i0_golden_corpus_manifest.json"


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_i0_golden_corpus_manifest_is_sealed_and_declares_gaps():
    result = verify_input_corpus_manifest(_manifest(), repository_root=ROOT)
    assert result["status"] == "PASS", result["errors"]
    assert result["verified_entries"] == 7
    assert result["declared_gap_count"] >= 6


def test_i0_golden_corpus_verifier_fails_closed_on_hash_tampering():
    tampered = deepcopy(_manifest())
    tampered["entries"][0]["sha256"] = "0" * 64
    result = verify_input_corpus_manifest(tampered, repository_root=ROOT)
    assert result["status"] == "FAIL"
    assert any("sha256 mismatch" in error for error in result["errors"])


def test_i0_golden_corpus_verifier_rejects_path_escape():
    tampered = deepcopy(_manifest())
    tampered["entries"][0]["path"] = "../outside.txt"
    result = verify_input_corpus_manifest(tampered, repository_root=ROOT)
    assert result["status"] == "FAIL"
    assert any("escapes repository root" in error for error in result["errors"])
