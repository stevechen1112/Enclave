from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts" / "run_p5_capacity.py"
    spec = importlib.util.spec_from_file_location("test_run_p5_capacity", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_process_escalates_from_terminate_to_kill():
    module = _module()

    class Process:
        returncode = None

        def __init__(self):
            self.terminated = False
            self.killed = False
            self.waits = 0

        def poll(self):
            return None if not self.killed else -9

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("capacity", timeout)
            self.returncode = -9
            return -9

    process = Process()
    assert module._stop_process(process, timeout=1) == -9
    assert process.terminated is True
    assert process.killed is True


def test_stop_process_preserves_completed_exit_code():
    module = _module()

    class Process:
        returncode = 7

        def poll(self):
            return 7

    assert module._stop_process(Process()) == 7
