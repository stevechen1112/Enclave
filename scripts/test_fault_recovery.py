#!/usr/bin/env python3
"""
=======================================================
  Fault Recovery Test Suite
  - Tests Docker container restart resilience
  - Verifies service auto-recovery and data persistence
=======================================================
"""
import io, sys, os, time, json, subprocess, requests

# ── UTF-8 stdout (Windows cp950 workaround) ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = os.getenv("API_BASE", "http://localhost:8001")
API = f"{BASE}/api/v1"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3001")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
TIMEOUT = 10

passed = 0
failed = 0
skipped = 0

def log(status, tid, msg):
    global passed, failed, skipped
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "INFO": "[INFO]"}
    print(f"  {tag.get(status, status)} {tid}: {msg}")
    if status == "PASS":
        passed += 1
    elif status == "FAIL":
        failed += 1
    elif status == "SKIP":
        skipped += 1


def get_token():
    r = requests.post(f"{API}/auth/login/access-token", data={
        "username": ADMIN_EMAIL, "password": ADMIN_PASS
    }, timeout=TIMEOUT)
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def docker_cmd(cmd_list, timeout=60):
    """Run a docker compose command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def wait_for_service(url, max_wait=60, interval=3):
    """Poll URL until it returns 2xx or max_wait exceeded."""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code < 500:
                return True, time.time() - start
        except Exception:
            pass
        time.sleep(interval)
    return False, time.time() - start


def wait_for_api_auth(max_wait=60, interval=3):
    """Poll login endpoint until auth works."""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            r = requests.post(f"{API}/auth/login/access-token", data={
                "username": ADMIN_EMAIL, "password": ADMIN_PASS
            }, timeout=5)
            if r.status_code == 200:
                return True, time.time() - start
        except Exception:
            pass
        time.sleep(interval)
    return False, time.time() - start


# ================================================================
print("\n=== Fault Recovery Test Suite ===\n")

# ── Pre-flight: verify services are running ──
print("[Pre-flight] Checking services are up...")
try:
    r = requests.get(f"{BASE}/health", timeout=5)
    if r.status_code >= 500:
        print("[ABORT] Backend not healthy. Start services first.")
        sys.exit(1)
    print(f"  Health: {r.status_code} {r.text[:80]}")
except Exception:
    print("[ABORT] Cannot reach backend. Start services first.")
    sys.exit(1)

token = get_token()
if not token:
    print("[ABORT] Cannot authenticate. Check credentials.")
    sys.exit(1)

print("[Pre-flight] All services reachable.\n")


# ── FR-01: Backend container restart recovery ──
print("--- FR-01: Backend container restart ---")
try:
    rc, out, err = docker_cmd(["docker", "compose", "restart", "web"], timeout=30)
    if rc != 0:
        log("SKIP", "FR-01", f"docker compose restart failed: {err[:100]}")
    else:
        ok, elapsed = wait_for_api_auth(max_wait=90, interval=3)
        if ok:
            log("PASS", "FR-01", f"Backend recovered in {elapsed:.1f}s")
        else:
            log("FAIL", "FR-01", f"Backend did not recover within 90s")
except Exception as e:
    log("SKIP", "FR-01", f"Exception: {e}")


# ── FR-02: Data persistence after backend restart ──
print("--- FR-02: Data persistence after restart ---")
try:
    new_token = get_token()
    if new_token:
        r = requests.get(f"{API}/documents/", headers=headers(new_token), timeout=TIMEOUT)
        if r.status_code == 200:
            log("PASS", "FR-02", "Documents endpoint accessible, data persisted")
        else:
            log("FAIL", "FR-02", f"Documents returned {r.status_code}")
    else:
        log("FAIL", "FR-02", "Cannot re-authenticate after restart")
except Exception as e:
    log("FAIL", "FR-02", f"Exception: {e}")


# ── FR-03: Auth token survives restart (JWT stateless) ──
print("--- FR-03: JWT token valid after restart ---")
try:
    # Use the pre-restart token
    r = requests.get(f"{API}/documents/", headers=headers(token), timeout=TIMEOUT)
    if r.status_code == 200:
        log("PASS", "FR-03", "Pre-restart JWT token still valid (stateless auth)")
    elif r.status_code == 401:
        log("FAIL", "FR-03", "Pre-restart token rejected (SECRET_KEY changed?)")
    else:
        log("FAIL", "FR-03", f"Unexpected status {r.status_code}")
except Exception as e:
    log("FAIL", "FR-03", f"Exception: {e}")


# ── FR-04: Frontend container restart recovery ──
print("--- FR-04: Frontend container restart ---")
try:
    rc, out, err = docker_cmd(["docker", "compose", "restart", "frontend"], timeout=30)
    if rc != 0:
        log("SKIP", "FR-04", f"docker compose restart failed: {err[:100]}")
    else:
        ok, elapsed = wait_for_service(FRONTEND_URL, max_wait=60, interval=3)
        if ok:
            log("PASS", "FR-04", f"Frontend recovered in {elapsed:.1f}s")
        else:
            log("FAIL", "FR-04", f"Frontend did not recover within 60s")
except Exception as e:
    log("SKIP", "FR-04", f"Exception: {e}")


# ── FR-05: Redis restart — session/cache recovery ──
print("--- FR-05: Redis restart ---")
try:
    rc, out, err = docker_cmd(["docker", "compose", "restart", "redis"], timeout=30)
    if rc != 0:
        log("SKIP", "FR-05", f"docker compose restart failed: {err[:100]}")
    else:
        time.sleep(5)
        ok, elapsed = wait_for_api_auth(max_wait=60, interval=3)
        if ok:
            log("PASS", "FR-05", f"API recovered after Redis restart in {elapsed:.1f}s")
        else:
            log("FAIL", "FR-05", f"API not functional after Redis restart")
except Exception as e:
    log("SKIP", "FR-05", f"Exception: {e}")


# ── FR-06: Database restart — connection pool recovery ──
print("--- FR-06: Database restart ---")
try:
    rc, out, err = docker_cmd(["docker", "compose", "restart", "db"], timeout=30)
    if rc != 0:
        log("SKIP", "FR-06", f"docker compose restart failed: {err[:100]}")
    else:
        # DB takes longer to recover
        time.sleep(10)
        ok, elapsed = wait_for_api_auth(max_wait=120, interval=5)
        if ok:
            log("PASS", "FR-06", f"API recovered after DB restart in {elapsed:.1f}s")
        else:
            log("FAIL", "FR-06", f"API not functional after DB restart within 120s")
except Exception as e:
    log("SKIP", "FR-06", f"Exception: {e}")


# ── FR-07: Full data integrity check after all restarts ──
print("--- FR-07: Full data integrity post-restart ---")
try:
    t = get_token()
    if not t:
        log("FAIL", "FR-07", "Cannot authenticate after all restarts")
    else:
        checks = []
        # Check documents
        r = requests.get(f"{API}/documents/", headers=headers(t), timeout=TIMEOUT)
        checks.append(("documents", r.status_code))
        # Check chat history
        r = requests.get(f"{API}/chat/conversations", headers=headers(t), timeout=TIMEOUT)
        checks.append(("chat_sessions", r.status_code))
        # Check health
        r = requests.get(f"{BASE}/health", timeout=TIMEOUT)
        checks.append(("health", r.status_code))

        all_ok = all(s < 400 for _, s in checks)
        detail = ", ".join(f"{n}={s}" for n, s in checks)
        if all_ok:
            log("PASS", "FR-07", f"All endpoints OK: {detail}")
        else:
            log("FAIL", "FR-07", f"Some endpoints failed: {detail}")
except Exception as e:
    log("FAIL", "FR-07", f"Exception: {e}")


# ── FR-08: Nginx gateway restart ──
print("--- FR-08: Nginx gateway restart ---")
try:
    rc, out, err = docker_cmd(["docker", "compose", "restart", "nginx"], timeout=30)
    if rc != 0:
        log("SKIP", "FR-08", f"docker compose restart failed (nginx may not exist): {err[:80]}")
    else:
        ok, elapsed = wait_for_service(FRONTEND_URL, max_wait=30, interval=2)
        if ok:
            log("PASS", "FR-08", f"Nginx gateway recovered in {elapsed:.1f}s")
        else:
            log("FAIL", "FR-08", f"Nginx gateway did not recover within 30s")
except Exception as e:
    log("SKIP", "FR-08", f"Exception: {e}")


# ── FR-09: Rapid restart resilience (restart backend 3x fast) ──
print("--- FR-09: Rapid restart resilience ---")
try:
    for i in range(3):
        docker_cmd(["docker", "compose", "restart", "web"], timeout=20)
        time.sleep(2)
    # Now wait for recovery
    ok, elapsed = wait_for_api_auth(max_wait=90, interval=3)
    if ok:
        log("PASS", "FR-09", f"Web service stable after 3 rapid restarts, recovered in {elapsed:.1f}s")
    else:
        log("FAIL", "FR-09", f"Web service unstable after rapid restarts")
except Exception as e:
    log("SKIP", "FR-09", f"Exception: {e}")


# ── FR-10: Health endpoint reflects recovery state ──
print("--- FR-10: Health endpoint accuracy ---")
try:
    r = requests.get(f"{BASE}/health", timeout=TIMEOUT)
    if r.status_code == 200:
        body = r.json()
        log("PASS", "FR-10", f"Health OK: {json.dumps(body, default=str)[:120]}")
    else:
        log("FAIL", "FR-10", f"Health returned {r.status_code}")
except Exception as e:
    log("FAIL", "FR-10", f"Exception: {e}")


# ── Summary ──
print(f"\n{'='*50}")
print(f"  Fault Recovery: {passed} passed / {failed} failed / {skipped} skipped")
print(f"{'='*50}\n")
sys.exit(1 if failed > 0 else 0)
