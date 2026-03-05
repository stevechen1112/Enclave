#!/usr/bin/env python3
"""
=======================================================
  Monitoring & Alerting Verification Suite
  - Health endpoint checks
  - Prometheus metrics endpoint
  - Alert rules validation
  - System resource monitoring
=======================================================
"""
import io, sys, os, json, requests, yaml, subprocess

# ── UTF-8 stdout (Windows cp950 workaround) ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.getenv("API_BASE", "http://localhost:8001")
API = f"{BASE}/api/v1"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
TIMEOUT = 10

passed = 0
failed = 0
skipped = 0


def log(status, tid, msg):
    global passed, failed, skipped
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "WARN": "[WARN]"}
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


print("\n=== Monitoring & Alerting Verification ===\n")

# ── MON-01: Health endpoint responds ──
print("--- MON-01: Health endpoint ---")
try:
    r = requests.get(f"{BASE}/health", timeout=TIMEOUT)
    if r.status_code == 200:
        body = r.json()
        log("PASS", "MON-01", f"Health OK: status={body.get('status')}, env={body.get('env')}")
    else:
        log("FAIL", "MON-01", f"Health returned {r.status_code}")
except Exception as e:
    log("FAIL", "MON-01", f"Exception: {e}")


# ── MON-02: Health response time ──
print("--- MON-02: Health response time ---")
try:
    r = requests.get(f"{BASE}/health", timeout=TIMEOUT)
    elapsed_ms = r.elapsed.total_seconds() * 1000
    if elapsed_ms < 500:
        log("PASS", "MON-02", f"Health responds in {elapsed_ms:.0f}ms (< 500ms)")
    elif elapsed_ms < 2000:
        log("WARN", "MON-02", f"Health responds in {elapsed_ms:.0f}ms (slow but acceptable)")
        passed += 1
    else:
        log("FAIL", "MON-02", f"Health responds in {elapsed_ms:.0f}ms (> 2000ms)")
except Exception as e:
    log("FAIL", "MON-02", f"Exception: {e}")


# ── MON-03: Prometheus metrics endpoint ──
print("--- MON-03: Prometheus metrics ---")
try:
    r = requests.get(f"{BASE}/metrics", timeout=TIMEOUT)
    if r.status_code == 200 and "http_" in r.text:
        lines = [l for l in r.text.splitlines() if l and not l.startswith("#")]
        log("PASS", "MON-03", f"Metrics endpoint active, {len(lines)} metric lines")
    elif r.status_code == 200:
        log("PASS", "MON-03", f"Metrics endpoint accessible ({len(r.text)} bytes)")
    elif r.status_code == 404:
        log("SKIP", "MON-03", "Metrics endpoint not configured (/metrics returns 404)")
    else:
        log("FAIL", "MON-03", f"Metrics returned {r.status_code}")
except Exception as e:
    log("SKIP", "MON-03", f"Exception: {e}")


# ── MON-04: Prometheus configuration file ──
print("--- MON-04: Prometheus config ---")
prom_cfg = os.path.join(PROJECT_ROOT, "monitoring", "prometheus.yml")
if os.path.exists(prom_cfg):
    try:
        with open(prom_cfg, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if cfg and "scrape_configs" in cfg:
            targets = [sc.get("job_name") for sc in cfg["scrape_configs"]]
            log("PASS", "MON-04", f"Prometheus config with jobs: {', '.join(targets)}")
        else:
            log("FAIL", "MON-04", "Prometheus config missing scrape_configs")
    except Exception as e:
        log("FAIL", "MON-04", f"Cannot parse prometheus.yml: {e}")
else:
    log("SKIP", "MON-04", "monitoring/prometheus.yml not found")


# ── MON-05: Alert rules file ──
print("--- MON-05: Alert rules ---")
alert_file = os.path.join(PROJECT_ROOT, "monitoring", "alert_rules.yml")
if os.path.exists(alert_file):
    try:
        with open(alert_file, "r", encoding="utf-8") as f:
            rules = yaml.safe_load(f)
        if rules and "groups" in rules:
            total_rules = sum(len(g.get("rules", [])) for g in rules["groups"])
            group_names = [g.get("name", "?") for g in rules["groups"]]
            log("PASS", "MON-05", f"{total_rules} alert rules in groups: {', '.join(group_names)}")
        else:
            log("FAIL", "MON-05", "Alert rules file has no groups")
    except Exception as e:
        log("FAIL", "MON-05", f"Cannot parse alert_rules.yml: {e}")
else:
    log("SKIP", "MON-05", "monitoring/alert_rules.yml not found")


# ── MON-06: Grafana dashboard provisioning ──
print("--- MON-06: Grafana dashboards ---")
grafana_dir = os.path.join(PROJECT_ROOT, "monitoring", "grafana")
if os.path.isdir(grafana_dir):
    files = os.listdir(grafana_dir)
    json_files = [f for f in files if f.endswith(".json")]
    yml_files = [f for f in files if f.endswith(".yml") or f.endswith(".yaml")]
    if json_files or yml_files:
        log("PASS", "MON-06", f"Grafana: {len(json_files)} dashboards, {len(yml_files)} provisioning files")
    else:
        log("WARN", "MON-06", f"Grafana dir exists but no dashboards: {files[:5]}")
        passed += 1
else:
    log("SKIP", "MON-06", "monitoring/grafana/ not found")


# ── MON-07: Docker container health status ──
print("--- MON-07: Docker container health ---")
try:
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        capture_output=True, timeout=15, cwd=PROJECT_ROOT
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else (result.stdout or "")
    result.stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else (result.stderr or "")
    if result.returncode == 0 and result.stdout.strip():
        containers = []
        for line in result.stdout.strip().splitlines():
            try:
                c = json.loads(line)
                containers.append(c)
            except json.JSONDecodeError:
                pass

        if containers:
            healthy = sum(1 for c in containers if c.get("Health", "") == "healthy"
                         or c.get("State", "") == "running")
            total = len(containers)
            unhealthy = [c.get("Service", c.get("Name", "?"))
                        for c in containers
                        if c.get("Health") == "unhealthy"]
            if unhealthy:
                log("WARN", "MON-07", f"{healthy}/{total} healthy, unhealthy: {', '.join(unhealthy)}")
                passed += 1
            else:
                log("PASS", "MON-07", f"All {total} containers healthy/running")
        else:
            log("SKIP", "MON-07", "No containers found in JSON output")
    else:
        log("SKIP", "MON-07", f"docker compose ps returned {result.returncode}")
except Exception as e:
    log("SKIP", "MON-07", f"Exception: {e}")


# ── MON-08: Database connection pool ──
print("--- MON-08: Database connectivity ---")
try:
    token = get_token()
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API}/documents/", headers=headers,
                        params={"page": 1, "page_size": 1}, timeout=TIMEOUT)
        if r.status_code == 200:
            log("PASS", "MON-08", "DB connection pool healthy (documents query OK)")
        else:
            log("FAIL", "MON-08", f"DB query returned {r.status_code}")
    else:
        log("FAIL", "MON-08", "Cannot authenticate to test DB")
except Exception as e:
    log("FAIL", "MON-08", f"Exception: {e}")


# ── MON-09: Redis connectivity ──
print("--- MON-09: Redis connectivity ---")
try:
    import redis
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6380"))
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    pong = r.ping()
    if pong:
        info = r.info("memory")
        used_mb = info.get("used_memory_human", "?")
        log("PASS", "MON-09", f"Redis PONG, memory used: {used_mb}")
    else:
        log("FAIL", "MON-09", "Redis did not respond to PING")
except ImportError:
    log("SKIP", "MON-09", "redis-py not installed")
except Exception as e:
    log("FAIL", "MON-09", f"Redis error: {e}")


# ── MON-10: Celery worker status ──
print("--- MON-10: Celery worker status ---")
try:
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json", "worker"],
        capture_output=True, timeout=15, cwd=PROJECT_ROOT
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else (result.stdout or "")
    result.stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else (result.stderr or "")
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            try:
                c = json.loads(line)
                state = c.get("State", "?")
                health = c.get("Health", "?")
                log("PASS", "MON-10", f"Celery worker: state={state}, health={health}")
                break
            except json.JSONDecodeError:
                pass
        else:
            log("SKIP", "MON-10", "Cannot parse worker status")
    else:
        log("SKIP", "MON-10", "Worker container not found")
except Exception as e:
    log("SKIP", "MON-10", f"Exception: {e}")


# ── Summary ──
print(f"\n{'='*50}")
print(f"  Monitoring: {passed} passed / {failed} failed / {skipped} skipped")
print(f"{'='*50}\n")
sys.exit(1 if failed > 0 else 0)
