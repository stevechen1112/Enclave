from app.services.asset_readiness import derive_asset_lifecycle, is_asset_answer_ready


def test_asset_lifecycle_is_mutually_exclusive_and_actionable():
    cases = [
        ({"answer_ready": False, "job_status": "failed", "asset_status": "failed", "pending_review_count": 0}, "needs_attention"),
        ({"answer_ready": False, "job_status": "running", "asset_status": "processing", "pending_review_count": 0}, "processing"),
        ({"answer_ready": True, "job_status": "ready", "asset_status": "active", "pending_review_count": 0}, "answer_ready"),
        ({"answer_ready": False, "job_status": "review_required", "asset_status": "review_required", "pending_review_count": 28}, "awaiting_review"),
        ({"answer_ready": False, "job_status": "ready", "asset_status": "active", "pending_review_count": 0}, "needs_attention"),
    ]

    for values, expected in cases:
        lifecycle, reasons = derive_asset_lifecycle(**values)
        assert lifecycle == expected
        assert (not reasons) is (expected == "answer_ready")


def test_failure_and_processing_take_precedence_over_stale_ready_flags():
    assert derive_asset_lifecycle(
        answer_ready=True,
        job_status="failed",
        asset_status="failed",
        pending_review_count=4,
    )[0] == "needs_attention"
    assert derive_asset_lifecycle(
        answer_ready=True,
        job_status="running",
        asset_status="processing",
        pending_review_count=4,
    )[0] == "processing"


def test_first_draft_needing_review_is_not_reported_as_answer_ready():
    assert not is_asset_answer_ready(
        document_ready=True,
        released_unit=False,
        job_status="review_required",
    )
    assert is_asset_answer_ready(
        document_ready=True,
        released_unit=False,
        job_status="ready",
    )
    assert is_asset_answer_ready(
        document_ready=True,
        released_unit=True,
        job_status="review_required",
    )
