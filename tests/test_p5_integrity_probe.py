from __future__ import annotations

from datetime import UTC

import pytest

from scripts.run_p5_integrity_probe import _job_revision_matches, _parse_time


@pytest.mark.parametrize(
    ("job_status", "revision_status"),
    [
        ("ready", "ready"),
        ("review_required", "review_required"),
        ("failed", "failed"),
        ("cancelled", "pending"),
    ],
)
def test_terminal_job_and_revision_states_reconcile(
    job_status: str, revision_status: str
) -> None:
    assert _job_revision_matches(job_status, revision_status)


@pytest.mark.parametrize(
    ("job_status", "revision_status"),
    [("queued", "pending"), ("running", "processing"), ("ready", "failed")],
)
def test_nonterminal_or_conflicting_states_do_not_reconcile(
    job_status: str, revision_status: str
) -> None:
    assert not _job_revision_matches(job_status, revision_status)


def test_probe_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _parse_time("2026-08-28T12:00:00")
    assert _parse_time("2026-08-28T12:00:00+08:00").tzinfo == UTC
