"""Phase 6 — Agent tool sandbox with hardened Docker isolation."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_IMAGES = {
    "alpine:3.19",
    "python:3.12-slim",
    "pipeshubai/pipeshub-sandbox:latest",
}

# Optional custom seccomp profile path. Empty / "default" → use Docker built-in
# (do NOT pass --security-opt seccomp=default; Docker treats it as a file path).
CUSTOM_SECCOMP = os.getenv("ENCLAVE_SANDBOX_SECCOMP", "").strip()


@dataclass
class SandboxResult:
    success: bool
    output: str = ""
    error: Optional[str] = None
    exit_code: int = 0


class AgentSandbox:
    """
    Hardened sandbox:
      - image allowlist
      - read-only rootfs + tmpfs workdir
      - --network=none（預設）或僅允許 egress proxy 環境變數指定的網路
      - --cap-drop ALL + no-new-privileges
      - optional custom seccomp profile file
      - optional --user (rootless-style non-root)
      - CPU / memory / pids / time limits
      - 不注入 secrets
    """

    def __init__(
        self,
        memory_mb: int = 256,
        cpu_quota: int = 50000,
        timeout_seconds: int = 30,
        network_disabled: bool = True,
        run_as_user: str = "65534:65534",
        pids_limit: int = 64,
    ):
        self.memory_mb = memory_mb
        self.cpu_quota = cpu_quota
        self.timeout_seconds = timeout_seconds
        self.network_disabled = network_disabled
        self.run_as_user = run_as_user
        self.pids_limit = pids_limit
        self.egress_proxy = os.getenv("ENCLAVE_SANDBOX_EGRESS_PROXY", "").strip()

    def run(self, image: str, command: List[str], workdir_files: Optional[Dict[str, bytes]] = None) -> SandboxResult:
        if image not in ALLOWED_IMAGES:
            return SandboxResult(success=False, error=f"image not allowlisted: {image}", exit_code=1)

        # 若啟用網路但未設 egress allowlist proxy → fail closed
        if not self.network_disabled and not self.egress_proxy:
            return SandboxResult(
                success=False,
                error="network requested but ENCLAVE_SANDBOX_EGRESS_PROXY not set (fail closed)",
                exit_code=1,
            )

        with tempfile.TemporaryDirectory(prefix="enclave-sandbox-") as tmp:
            if workdir_files:
                for name, data in workdir_files.items():
                    safe = os.path.basename(name)
                    with open(os.path.join(tmp, safe), "wb") as f:
                        f.write(data)

            cmd = [
                "docker", "run", "--rm",
                f"--memory={self.memory_mb}m",
                f"--cpus={self.cpu_quota / 100000:.2f}",
                f"--pids-limit={self.pids_limit}",
                "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL",
                "--user", self.run_as_user,
            ]
            if CUSTOM_SECCOMP and CUSTOM_SECCOMP.lower() not in ("default", "none", "off"):
                cmd.extend(["--security-opt", f"seccomp={CUSTOM_SECCOMP}"])

            if self.network_disabled:
                cmd.append("--network=none")
            else:
                cmd.extend(["-e", f"HTTPS_PROXY={self.egress_proxy}", "-e", f"HTTP_PROXY={self.egress_proxy}"])

            cmd.extend(["-v", f"{tmp}:/work:ro", "-w", "/work", image, *command])

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self.timeout_seconds,
                    env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                )
                out = proc.stdout[:4000]
                if _looks_like_secret_dump(out):
                    return SandboxResult(success=False, error="output blocked by secret scanner", exit_code=1)
                return SandboxResult(
                    success=proc.returncode == 0,
                    output=out,
                    error=proc.stderr[:1000] if proc.stderr else None,
                    exit_code=proc.returncode,
                )
            except subprocess.TimeoutExpired:
                return SandboxResult(success=False, error="sandbox timeout", exit_code=124)
            except FileNotFoundError:
                return SandboxResult(success=False, error="docker not available", exit_code=127)
            except Exception as exc:
                return SandboxResult(success=False, error=str(exc), exit_code=1)


def _looks_like_secret_dump(text: str) -> bool:
    lowered = text.lower()
    needles = ("begin private key", "aws_secret_access_key", "password=", "api_key=")
    return any(n in lowered for n in needles)
