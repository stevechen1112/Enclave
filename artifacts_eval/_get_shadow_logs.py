"""用 UTF-8 正確擷取容器內 source_verify 日誌。"""
import io
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

out = subprocess.run(
    ["docker", "logs", "enclave-web-1", "--since", "10m"],
    capture_output=True,
)
text = out.stdout.decode("utf-8", "replace") + out.stderr.decode("utf-8", "replace")
for line in text.splitlines():
    if "source_verify" in line:
        print(line.split("| ")[-1].strip()[:500])
