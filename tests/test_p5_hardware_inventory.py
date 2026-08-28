from unittest.mock import MagicMock, patch

from app.services.hardware_inventory import (
    co_resident_enclave_projects,
    compose_container_identity,
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


def test_metrics_container_must_belong_to_target_compose_project():
    completed = MagicMock(
        returncode=0,
        stdout=(
            '{"com.docker.compose.project":"enclave-p5",'
            '"com.docker.compose.service":"web"}\t'
            '{"Running":true}\t"sha256:abc"\n'
        ),
    )
    with patch("subprocess.run", return_value=completed):
        identity = compose_container_identity("enclave-p5-web-1", "enclave-p5")
    assert identity == {
        "container": "enclave-p5-web-1",
        "compose_project": "enclave-p5",
        "compose_service": "web",
        "running": True,
        "image_id": "sha256:abc",
    }


def test_metrics_container_rejects_production_project():
    completed = MagicMock(
        returncode=0,
        stdout=(
            '{"com.docker.compose.project":"enclave",'
            '"com.docker.compose.service":"web"}\t'
            '{"Running":true}\t"sha256:prod"\n'
        ),
    )
    with patch("subprocess.run", return_value=completed):
        try:
            compose_container_identity("enclave-web-1", "enclave-p5")
        except ValueError as exc:
            assert "not a running member" in str(exc)
        else:
            raise AssertionError("production container binding was accepted")
