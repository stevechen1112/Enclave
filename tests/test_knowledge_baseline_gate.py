import hashlib

from scripts.eval_knowledge_baseline_gate import (
    citation_is_cross_process_stable,
    legacy_eval_is_unchanged,
)


def test_citation_revision_is_stable_across_real_processes():
    assert citation_is_cross_process_stable() is True


def test_legacy_eval_integrity_detects_changed_file(tmp_path, monkeypatch):
    import scripts.eval_knowledge_baseline_gate as gate

    monkeypatch.setattr(gate, "ROOT", tmp_path)
    paths = [tmp_path / f"result-{index}.json" for index in range(4)]
    for path in paths:
        path.write_text("original", encoding="utf-8")
    payload = {"files": {path.name: hashlib.sha256(b"original").hexdigest() for path in paths}}
    assert legacy_eval_is_unchanged(payload) is True
    paths[2].write_text("changed", encoding="utf-8")
    assert legacy_eval_is_unchanged(payload) is False
