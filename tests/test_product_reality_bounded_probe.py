from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "product_reality_bounded_probe",
    ROOT / "scripts" / "run_product_reality_bounded_probe.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_percentile_uses_nearest_rank() -> None:
    assert MODULE._percentile([1, 2, 3, 4], 0.50) == 2
    assert MODULE._percentile([1, 2, 3, 4], 0.95) == 4
    assert MODULE._percentile([], 0.95) == 0


@pytest.mark.parametrize(
    ("concurrency", "request_count"), ((0, 10), (51, 100), (10, 9), (10, 201))
)
def test_probe_rejects_unsafe_bounds(concurrency: int, request_count: int) -> None:
    class UnusedClient:
        pass

    with pytest.raises(ValueError):
        MODULE.run_probe(
            client=UnusedClient(),
            username="unused",
            password="unused",
            expected_tenant_id="unused",
            expected_release_id="unused",
            concurrency=concurrency,
            request_count=request_count,
        )
