from scripts.profile_knowledge_capacity import profile_verdict


def test_capacity_profile_requires_quality_scope_and_latency():
    limits = {"p95_ms": 750, "p99_ms": 1500}
    metrics = {
        "error_rate": 0,
        "scope_violations": 0,
        "hit_at_10": .92,
        "p95_ms": 500,
        "p99_ms": 900,
    }
    assert profile_verdict(metrics, limits, baseline_hit_rate=.90) == ("PASS", [])

    metrics["scope_violations"] = 1
    metrics["hit_at_10"] = .80
    status, reasons = profile_verdict(metrics, limits, baseline_hit_rate=.90)
    assert status == "FAIL"
    assert "tenant_acl_or_revision_scope_violation" in reasons
    assert "retrieval_quality_below_baseline" in reasons


def test_capacity_profile_rejects_errors_and_tail_latency():
    limits = {"p95_ms": 750, "p99_ms": 1500}
    metrics = {
        "error_rate": .01,
        "scope_violations": 0,
        "hit_at_10": 1,
        "p95_ms": 800,
        "p99_ms": 1600,
    }
    status, reasons = profile_verdict(metrics, limits, baseline_hit_rate=.90)
    assert status == "FAIL"
    assert set(reasons) == {
        "query_errors_present",
        "p95_above_profile_limit",
        "p99_above_profile_limit",
    }
