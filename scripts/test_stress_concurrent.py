#!/usr/bin/env python3
"""
=======================================================
  Stress / Concurrency Test Suite (Locust-based)
  - Simulates concurrent users on key API endpoints
  - Runs headless with programmatic results
=======================================================
"""
import io, sys, os, json, time

# ── UTF-8 stdout (Windows cp950 workaround) ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Configuration ──
HOST = os.getenv("API_HOST", "http://localhost:8001")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
USERS = int(os.getenv("STRESS_USERS", "10"))
SPAWN_RATE = int(os.getenv("STRESS_SPAWN_RATE", "5"))
DURATION_SEC = int(os.getenv("STRESS_DURATION", "30"))

print(f"\n=== Stress / Concurrency Test Suite ===")
print(f"  Host: {HOST}")
print(f"  Users: {USERS}, Spawn Rate: {SPAWN_RATE}/s, Duration: {DURATION_SEC}s\n")

# ── Create locustfile dynamically ──
LOCUSTFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_locustfile_tmp.py")
CSV_PREFIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stress_results")

locust_code = f'''
import os
from locust import HttpUser, task, between, events

TOKEN = None

class EnclaveUser(HttpUser):
    wait_time = between(0.5, 2)
    host = "{HOST}"

    def on_start(self):
        global TOKEN
        if TOKEN is None:
            r = self.client.post(
                "/api/v1/auth/login/access-token",
                data={{"username": "{ADMIN_EMAIL}", "password": "{ADMIN_PASS}"}},
                name="auth/login"
            )
            if r.status_code == 200:
                TOKEN = r.json().get("access_token")
        self.token = TOKEN
        self.headers = {{"Authorization": f"Bearer {{self.token}}"}} if self.token else {{}}

    @task(5)
    def health_check(self):
        self.client.get("/health", name="health")

    @task(3)
    def list_documents(self):
        self.client.get("/api/v1/documents/", headers=self.headers, name="documents/list")

    @task(2)
    def list_conversations(self):
        self.client.get("/api/v1/chat/conversations", headers=self.headers, name="chat/conversations")

    @task(2)
    def analytics_summary(self):
        self.client.get("/api/v1/chat/analytics/summary", headers=self.headers, name="analytics/summary")

    @task(1)
    def search_documents(self):
        self.client.get(
            "/api/v1/documents/?search=test",
            headers=self.headers,
            name="documents/search"
        )

    @task(1)
    def supported_formats(self):
        self.client.get(
            "/api/v1/documents/supported-formats",
            headers=self.headers,
            name="documents/formats"
        )

    @task(1)
    def feature_flags(self):
        self.client.get("/api/v1/feature-flags/", headers=self.headers, name="feature-flags")
'''

with open(LOCUSTFILE, "w", encoding="utf-8") as f:
    f.write(locust_code)

# ── Run Locust headless ──
import subprocess

cmd = [
    sys.executable, "-m", "locust",
    "-f", LOCUSTFILE,
    "--headless",
    "--host", HOST,
    "-u", str(USERS),
    "-r", str(SPAWN_RATE),
    "-t", f"{DURATION_SEC}s",
    "--csv", CSV_PREFIX,
    "--only-summary",
]

print(f"Running: {' '.join(cmd)}\n")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=DURATION_SEC + 60)

# Print output
if result.stdout:
    for line in result.stdout.splitlines():
        print(f"  {line}")
if result.stderr:
    # Locust outputs stats to stderr
    for line in result.stderr.splitlines():
        if any(kw in line.lower() for kw in ["aggregated", "name", "fail", "avg", "rps", "error", "---", "|"]):
            print(f"  {line}")

# ── Parse CSV results ──
stats_file = f"{CSV_PREFIX}_stats.csv"
failures_file = f"{CSV_PREFIX}_failures.csv"

print(f"\n{'='*60}")
print("  STRESS TEST RESULTS")
print(f"{'='*60}")

total_requests = 0
total_failures = 0
p99_max = 0

if os.path.exists(stats_file):
    import csv
    with open(stats_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        for row in rows:
            name = row.get("Name", "")
            if name == "Aggregated":
                total_requests = int(row.get("Request Count", 0))
                total_failures = int(row.get("Failure Count", 0))
                avg_rt = row.get("Average Response Time", "?")
                p99 = row.get("99%", "?")
                rps = row.get("Requests/s", "?")
                print(f"  Total Requests:   {total_requests}")
                print(f"  Total Failures:   {total_failures}")
                print(f"  Avg Response:     {avg_rt} ms")
                print(f"  P99 Response:     {p99} ms")
                print(f"  Requests/sec:     {rps}")
            else:
                p99_val = float(row.get("99%", 0) or 0)
                if p99_val > p99_max:
                    p99_max = p99_val

    # Per-endpoint breakdown
    print(f"\n  --- Per-Endpoint ---")
    for row in rows:
        name = row.get("Name", "")
        if name and name != "Aggregated":
            count = row.get("Request Count", "?")
            fails = row.get("Failure Count", "?")
            avg = row.get("Average Response Time", "?")
            p99 = row.get("99%", "?")
            print(f"  {name:30s}  reqs={count:>5s}  fail={fails:>3s}  avg={avg:>6s}ms  p99={p99:>6s}ms")

# ── Verdict ──
fail_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
print(f"\n{'='*60}")

passed = 0
failed = 0

# Criterion 1: Error rate < 5%
if fail_rate < 5:
    print(f"  [PASS] ST-01: Error rate {fail_rate:.1f}% < 5% threshold")
    passed += 1
else:
    print(f"  [FAIL] ST-01: Error rate {fail_rate:.1f}% >= 5% threshold")
    failed += 1

# Criterion 2: P99 < 5000ms
if p99_max < 5000:
    print(f"  [PASS] ST-02: P99 max {p99_max:.0f}ms < 5000ms threshold")
    passed += 1
else:
    print(f"  [FAIL] ST-02: P99 max {p99_max:.0f}ms >= 5000ms threshold")
    failed += 1

# Criterion 3: At least some requests completed
if total_requests > 0:
    print(f"  [PASS] ST-03: {total_requests} requests completed successfully")
    passed += 1
else:
    print(f"  [FAIL] ST-03: No requests completed")
    failed += 1

print(f"\n  Stress Test: {passed} passed / {failed} failed")
print(f"{'='*60}\n")

# ── Cleanup ──
os.remove(LOCUSTFILE)
for f in [stats_file, failures_file, f"{CSV_PREFIX}_stats_history.csv",
          f"{CSV_PREFIX}_exceptions.csv", f"{CSV_PREFIX}_failures.csv"]:
    if os.path.exists(f):
        os.remove(f)

sys.exit(1 if failed > 0 else 0)
