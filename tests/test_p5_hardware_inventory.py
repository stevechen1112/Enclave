from app.services.hardware_inventory import hardware_shortfalls


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
