from unittest.mock import MagicMock, patch

from app.services.hardware_inventory import (
    co_resident_enclave_projects,
    hardware_shortfalls,
)


def test_hardware_shortfalls_are_explicit_and_fail_closed():
    required = {"cpu_cores": 8, "ram_gb": 32, "disk_gb": 200, "gpu_vram_gb": 8}
    observed = {"cpu_cores": 4, "ram_gb": 8.2, "disk_gb": 160, "gpu_vram_gb": 0}
    errors = hardware_shortfalls(observed, required)
    assert len(errors) == 4
    assert errors[0] == "cpu_cores: observed 4, requires 8"


def test_hardware_shortfalls_accept_qualified_host():
    required = {"cpu_cores": 4, "ram_gb": 8, "disk_gb": 50, "gpu_vram_gb": 0}
    observed = {"cpu_cores": 4, "ram_gb": 8.2, "disk_gb": 160, "gpu_vram_gb": 0}
    assert hardware_shortfalls(observed, required) == []


def test_capacity_host_rejects_other_enclave_compose_project():
    completed = MagicMock(
        returncode=0,
        stdout=(
            "enclave-staging\tenclave-staging-web-1\tenclave-staging/backend:test\n"
            "enclave\tenclave-web-1\tenclave/backend:prod\n"
            "unrelated\tmailpit-1\taxllent/mailpit:latest\n"
        ),
    )
    with patch("subprocess.run", return_value=completed):
        assert co_resident_enclave_projects("enclave-staging") == ["enclave"]


def test_capacity_host_inspection_fails_closed():
    with patch("subprocess.run", side_effect=OSError("docker unavailable")):
        assert co_resident_enclave_projects("enclave-staging") == [
            "docker-inspection-unavailable:OSError"
        ]
