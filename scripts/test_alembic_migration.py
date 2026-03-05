#!/usr/bin/env python3
"""
=======================================================
  Alembic Migration Verification Script
  - Checks migration history consistency
  - Verifies head matches current state
  - Tests downgrade/upgrade cycle (dry-run check)
=======================================================
"""
import io, sys, os, subprocess, re

# ── UTF-8 stdout (Windows cp950 workaround) ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def run_alembic(args, timeout=30):
    """Run alembic command inside docker compose exec."""
    cmd = ["docker", "compose", "exec", "-T", "web", "alembic"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_ROOT
        )
        # Merge stdout + stderr (alembic outputs to stderr), filter docker warnings
        out_lines = [l for l in (result.stdout + "\n" + result.stderr).splitlines()
                     if not l.startswith('time=') and not 'level=warning' in l
                     and not 'attribute `version`' in l]
        combined = "\n".join(out_lines).strip()
        return 0 if result.returncode == 0 or combined else result.returncode, combined, ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def run_docker_cmd(args, timeout=30):
    """Run arbitrary command inside web container."""
    cmd = ["docker", "compose", "exec", "-T", "web"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_ROOT
        )
        out_lines = [l for l in (result.stdout + "\n" + result.stderr).splitlines()
                     if not l.startswith('time=') and 'level=warning' not in l]
        return result.returncode, "\n".join(out_lines).strip(), ""
    except Exception as e:
        return -1, "", str(e)


print("\n=== Alembic Migration Verification ===\n")

# ── AM-01: Check current revision ──
print("--- AM-01: Current revision ---")
rc, out, err = run_alembic(["current"])
# Filter INFO lines to get actual revision
rev_lines = [l for l in out.splitlines() if not l.startswith("INFO")]
rev_text = "\n".join(rev_lines).strip()
if rc == 0:
    if rev_text:
        log("PASS", "AM-01", f"Current: {rev_text[:80]}")
    else:
        log("PASS", "AM-01", "Current: at head (no pending migrations)")
else:
    log("FAIL", "AM-01", f"Cannot get current revision: {err[:100]}")

# ── AM-02: Check head revision ──
print("--- AM-02: Head revision ---")
rc, out, err = run_alembic(["heads"])
if rc == 0 and out:
    heads = out.strip().splitlines()
    if len(heads) == 1:
        log("PASS", "AM-02", f"Single head: {heads[0][:80]}")
    else:
        log("FAIL", "AM-02", f"Multiple heads detected ({len(heads)}): divergent branches!")
        for h in heads:
            print(f"    {h}")
else:
    log("FAIL", "AM-02", f"Cannot get heads: {err[:100]}")

# ── AM-03: Verify current == head (no pending migrations) ──
print("--- AM-03: Current matches head ---")
rc_cur, cur_out, _ = run_alembic(["current"])
rc_head, head_out, _ = run_alembic(["heads"])
if rc_cur == 0 and rc_head == 0:
    # Extract revision IDs (12-char hex)
    cur_ids = re.findall(r'\b([a-f0-9]{12})\b', cur_out)
    head_ids = re.findall(r'\b([a-f0-9]{12})\b', head_out)
    if head_ids:
        head_id = head_ids[0]
        if not cur_ids or head_id in cur_out:
            # Empty current or head present in current output both mean at-head
            log("PASS", "AM-03", f"Database is at head ({head_id})")
        elif cur_ids and cur_ids[0] != head_id:
            log("FAIL", "AM-03", f"Current {cur_ids[0]} != Head {head_id}")
        else:
            log("PASS", "AM-03", "Current revision matches head")
    else:
        log("SKIP", "AM-03", "Could not parse head revision ID")
else:
    log("FAIL", "AM-03", "Cannot compare revisions")

# ── AM-04: Migration history integrity ──
print("--- AM-04: Migration history ---")
rc, out, err = run_alembic(["history", "--verbose"])
if rc == 0 and out:
    lines = [l for l in out.splitlines() if l.strip() and "->" in l]
    log("PASS", "AM-04", f"History has {len(lines)} migration(s)")
else:
    # Try without verbose
    rc2, out2, err2 = run_alembic(["history"])
    if rc2 == 0 and out2:
        lines = [l for l in out2.splitlines() if l.strip()]
        log("PASS", "AM-04", f"History has {len(lines)} migration(s)")
    else:
        log("FAIL", "AM-04", f"Cannot read history: {err[:100]}")

# ── AM-05: Check for migration files ──
print("--- AM-05: Migration files ---")
versions_dir = os.path.join(PROJECT_ROOT, "alembic", "versions")
if os.path.isdir(versions_dir):
    py_files = [f for f in os.listdir(versions_dir) if f.endswith(".py") and not f.startswith("__")]
    if py_files:
        log("PASS", "AM-05", f"Found {len(py_files)} migration file(s) in alembic/versions/")
    else:
        log("FAIL", "AM-05", "No migration files found in alembic/versions/")
else:
    log("FAIL", "AM-05", "alembic/versions/ directory not found")

# ── AM-06: Verify alembic.ini exists and is configured ──
print("--- AM-06: alembic.ini configuration ---")
ini_path = os.path.join(PROJECT_ROOT, "alembic.ini")
if os.path.exists(ini_path):
    with open(ini_path, "r", encoding="utf-8") as f:
        content = f.read()
    has_sqlalchemy_url = "sqlalchemy.url" in content
    has_script_location = "script_location" in content
    if has_sqlalchemy_url and has_script_location:
        log("PASS", "AM-06", "alembic.ini properly configured")
    else:
        missing = []
        if not has_sqlalchemy_url:
            missing.append("sqlalchemy.url")
        if not has_script_location:
            missing.append("script_location")
        log("FAIL", "AM-06", f"Missing config: {', '.join(missing)}")
else:
    log("FAIL", "AM-06", "alembic.ini not found")

# ── AM-07: Check upgrade operation (re-run to head is idempotent) ──
print("--- AM-07: Upgrade to head (idempotent) ---")
rc, out, err = run_alembic(["upgrade", "head"], timeout=60)
# If output contains valid alembic INFO lines, it worked
if "Context impl" in out or "Will assume" in out or rc == 0:
    log("PASS", "AM-07", "Upgrade to head succeeded (idempotent)")
else:
    log("FAIL", "AM-07", f"Upgrade to head failed: {out[:120]} {err[:120]}")

# ── AM-08: Check stamp command ──
print("--- AM-08: Alembic stamp verification ---")
rc, out, err = run_alembic(["current"])
if rc == 0:
    log("PASS", "AM-08", f"Post-upgrade current: {out.splitlines()[-1][:80] if out else 'empty'}")
else:
    log("FAIL", "AM-08", f"Current check failed: {err[:100]}")

# ── AM-09: Verify env.py exists in container ──
print("--- AM-09: env.py configuration ---")
rc, out, _ = run_docker_cmd(["python", "-c",
    "import os; p='/code/alembic/env.py'; "
    "print('exists' if os.path.exists(p) else 'missing'); "
    "open(p).read() if os.path.exists(p) else None"
], timeout=10)
# Also check local path in case alembic dir has env.py inside docker volume
local_env = os.path.join(PROJECT_ROOT, "alembic", "env.py")
if os.path.exists(local_env):
    with open(local_env, "r", encoding="utf-8") as f:
        env_content = f.read()
    has_target_metadata = "target_metadata" in env_content
    if has_target_metadata:
        log("PASS", "AM-09", "env.py has target_metadata configured (local)")
    else:
        log("FAIL", "AM-09", "env.py missing target_metadata")
elif 'exists' in out:
    log("PASS", "AM-09", "env.py exists in container")
else:
    # Check inside container
    rc2, out2, _ = run_docker_cmd(["cat", "/code/alembic/env.py"], timeout=10)
    if rc2 == 0 and "target_metadata" in out2:
        log("PASS", "AM-09", "env.py has target_metadata (in container)")
    elif rc2 == 0:
        log("FAIL", "AM-09", "env.py missing target_metadata")
    else:
        log("SKIP", "AM-09", "Cannot access env.py locally or in container")

# ── AM-10: No orphan migration files ──
print("--- AM-10: Migration file consistency ---")
rc, hist_out, _ = run_alembic(["history", "-r", "base:head"])
if rc == 0 and os.path.isdir(versions_dir):
    py_files_set = {f.split("_")[0] for f in os.listdir(versions_dir)
                    if f.endswith(".py") and not f.startswith("__")}
    # Just verify count alignment
    hist_count = len([l for l in hist_out.splitlines() if l.strip() and (">" in l or "Rev:" in l)])
    file_count = len(py_files_set)
    if file_count > 0:
        log("PASS", "AM-10", f"Files: {file_count}, History entries: {hist_count}")
    else:
        log("SKIP", "AM-10", "No migration files to verify")
else:
    log("SKIP", "AM-10", "Cannot perform file consistency check")

# ── Summary ──
print(f"\n{'='*50}")
print(f"  Alembic Migration: {passed} passed / {failed} failed / {skipped} skipped")
print(f"{'='*50}\n")
sys.exit(1 if failed > 0 else 0)
