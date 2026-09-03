from types import SimpleNamespace

from scripts.eval_knowledge_evaluation_gate import run_passes, seal_passes


def _passing_summary():
    return {
        "total": 200,
        "strict_assertions": {"rate": .95},
        "critical_errors": 0,
        "domain_distribution": {"manufacturing": 50, "legal": 50, "finance": 50, "operations": 50},
        "domain_quality": {
            name: {"denominator": 50, "rate": .90}
            for name in ("manufacturing", "legal", "finance", "operations")
        },
        "required_slot_coverage": {"denominator": 400, "rate": .98},
        "language_profile_distribution": {"standard": 160, "mixed": 40},
        "pipeline_invariant_violations": 0,
        "classification_quality": {
            "false_acceptance": {"numerator": 0, "denominator": 20, "rate": 0.0},
            "false_rejection": {"numerator": 1, "denominator": 100, "rate": .01},
            "partial_correctness": {"numerator": 20, "denominator": 20, "rate": 1.0},
            "conflict_correctness": {"numerator": 20, "denominator": 20, "rate": 1.0},
        },
    }


def test_evaluation_gate_enforces_platform_denominators():
    passed, reasons = run_passes(_passing_summary())
    assert passed is True
    assert reasons == []

    undersized = _passing_summary()
    undersized["total"] = 199
    undersized["language_profile_distribution"] = {"standard": 159, "mixed": 40}
    passed, reasons = run_passes(undersized)
    assert passed is False
    assert "case_count_below_200" in reasons


def test_evaluation_gate_requires_hash_bound_independent_seal():
    run = SimpleNamespace(
        corpus_hash="a" * 64,
        question_hash="b" * 64,
        runtime_manifest={
            "implementer": "developer-b",
            "holdout_seal": {
                "custodian": "qa-a",
                "corpus_manifest_sha256": "a" * 64,
                "questions_sha256": "b" * 64,
                "attestation_sha256": "c" * 64,
            },
        },
    )
    assert seal_passes(run) == (True, [])

    run.runtime_manifest["implementer"] = "QA-A"
    passed, reasons = seal_passes(run)
    assert passed is False
    assert "custodian_is_repair_implementer" in reasons
