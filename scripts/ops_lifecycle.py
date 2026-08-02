"""
Enclave ops lifecycle (Windows-friendly):
  install | upgrade | rollback | backup | remove | status

Examples:
  python scripts/ops_lifecycle.py preflight --profile lite
  python scripts/ops_lifecycle.py backup
  python scripts/ops_lifecycle.py upgrade --revision head
  python scripts/ops_lifecycle.py rollback --steps 1
  python scripts/ops_lifecycle.py install --profile lite
  python scripts/ops_lifecycle.py remove --profile lite
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "artifacts" / "ops"
COMPOSE_FILE = ROOT / "docker-compose.profiles.yml"


def _run(cmd: list[str], cwd: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
    )


def _docker_db_container() -> str | None:
    """Prefer running enclave db container name (works even without compose profile up)."""
    env_name = os.getenv("ENCLAVE_DB_CONTAINER", "").strip()
    if env_name:
        return env_name
    proc = _run(["docker", "ps", "--format", "{{.Names}}"])
    if proc.returncode != 0:
        return None
    names = [n.strip() for n in (proc.stdout or "").splitlines() if n.strip()]
    for candidate in ("enclave-db-1", "enclave-db", "db"):
        if candidate in names:
            return candidate
    for n in names:
        if "enclave" in n and "db" in n:
            return n
    return None


def _write_log(action: str, payload: dict) -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"{action}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def cmd_preflight(profile: str) -> int:
    from app.services.deployment import DeploymentProfile, run_preflight
    result = run_preflight(DeploymentProfile(profile))
    payload = {
        "action": "preflight",
        "profile": profile,
        "passed": result.passed,
        "checks": result.checks,
        "errors": result.errors,
        "warnings": result.warnings,
    }
    path = _write_log("preflight", payload)
    print(f"preflight passed={result.passed} log={path}")
    return 0 if result.passed else 1


def cmd_backup() -> int:
    import shutil
    import tarfile

    backup_dir = Path(os.getenv("BACKUP_DIR", str(ROOT / "backups")))
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"enclave_{ts}.sql"
    uploads_tar = backup_dir / f"uploads_{ts}.tgz"
    db_ok = False
    mode = "none"
    stderr = ""
    user = os.getenv("POSTGRES_USER", "postgres")
    dbname = os.getenv("POSTGRES_DB", "enclave")

    container = _docker_db_container()
    if container:
        mode = f"docker_exec:{container}"
        proc = _run(["docker", "exec", container, "pg_dump", "-U", user, dbname])
        stderr = proc.stderr or ""
        if proc.returncode == 0 and proc.stdout:
            out.write_text(proc.stdout, encoding="utf-8", errors="replace")
            db_ok = True

    if not db_ok:
        mode = "compose"
        compose = [
            "docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "lite",
            "exec", "-T", "db",
            "pg_dump", "-U", user, dbname,
        ]
        proc = _run(compose)
        stderr = proc.stderr or stderr
        if proc.returncode == 0 and proc.stdout:
            out.write_text(proc.stdout, encoding="utf-8", errors="replace")
            db_ok = True

    if not db_ok:
        mode = "pg_dump"
        pg_dump = [
            "pg_dump",
            "-h", os.getenv("POSTGRES_SERVER", "localhost"),
            "-p", os.getenv("POSTGRES_PORT", "5435"),
            "-U", user,
            "-d", dbname,
            "-f", str(out),
        ]
        env = os.environ.copy()
        env["PGPASSWORD"] = os.getenv("POSTGRES_PASSWORD", "postgres")
        print("+", " ".join(pg_dump))
        proc2 = subprocess.run(
            pg_dump, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        db_ok = proc2.returncode == 0 and out.exists() and out.stat().st_size > 0
        stderr = (proc2.stderr or stderr or "")[:500]

    uploads_dir = ROOT / "uploads"
    uploads_ok = False
    if uploads_dir.is_dir():
        with tarfile.open(uploads_tar, "w:gz") as tar:
            tar.add(str(uploads_dir), arcname="uploads", filter=_exclude_credential_paths)
        uploads_ok = uploads_tar.exists()
    else:
        uploads_tar.write_bytes(b"")  # empty placeholder marker
        uploads_ok = True

    # Never bundle connector vault into uploads backup (DD-M14)
    cred_dir = ROOT / "var" / "credentials"
    if cred_dir.is_dir() and any(cred_dir.iterdir()):
        payload_note = "credentials_excluded"
    else:
        payload_note = "credentials_empty_or_absent"

    ok = db_ok and uploads_ok
    payload = {
        "action": "backup",
        "status": "ok" if ok else "error",
        "path": str(out) if db_ok else None,
        "uploads_path": str(uploads_tar) if uploads_ok else None,
        "mode": mode,
        "credentials": payload_note,
        "stderr": stderr[:500],
    }
    _write_log("backup", payload)
    print("backup", payload["status"], payload.get("path"), payload.get("uploads_path"))
    return 0 if ok else 1


def _exclude_credential_paths(tarinfo: "tarfile.TarInfo"):
    """Omit leftover uploads/.credentials and never ship OAuth material."""
    name = tarinfo.name.replace("\\", "/").lower()
    parts = name.split("/")
    if ".credentials" in parts or name.endswith(".credentials"):
        return None
    if "var/credentials" in name or name.startswith("credentials/"):
        return None
    return tarinfo


def _safe_extract_tar(tar: "tarfile.TarFile", dest: Path) -> None:
    """Extract tar members only under dest (block path traversal)."""
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        try:
            target.relative_to(dest)
        except ValueError as exc:
            raise ValueError(f"tar path traversal blocked: {member.name}") from exc
    tar.extractall(path=str(dest))


def cmd_restore(sql_path: str, uploads_tar: str = "") -> int:
    import tarfile

    path = Path(sql_path)
    if not path.is_file():
        payload = {"action": "restore", "status": "error", "error": f"missing {sql_path}"}
        _write_log("restore", payload)
        print("restore error: file missing")
        return 1
    compose = [
        "docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "lite",
        "exec", "-T", "db",
        "psql", "-U", os.getenv("POSTGRES_USER", "postgres"),
        "-d", os.getenv("POSTGRES_DB", "enclave"),
    ]
    print("+", " ".join(compose), "<", str(path))
    proc = subprocess.run(
        compose, cwd=str(ROOT), input=path.read_text(encoding="utf-8", errors="replace"),
        capture_output=True, text=True,
    )
    ok = proc.returncode == 0
    if not ok:
        env = os.environ.copy()
        env["PGPASSWORD"] = os.getenv("POSTGRES_PASSWORD", "postgres")
        psql = [
            "psql",
            "-h", os.getenv("POSTGRES_SERVER", "localhost"),
            "-p", os.getenv("POSTGRES_PORT", "5435"),
            "-U", os.getenv("POSTGRES_USER", "postgres"),
            "-d", os.getenv("POSTGRES_DB", "enclave"),
            "-f", str(path),
        ]
        proc = subprocess.run(psql, env=env, capture_output=True, text=True)
        ok = proc.returncode == 0

    uploads_ok = True
    uploads_note = "skipped"
    tar_path = Path(uploads_tar) if uploads_tar else None
    if tar_path is None:
        # Convention: enclave_TS.sql → uploads_TS.tgz
        candidate = path.parent / path.name.replace("enclave_", "uploads_").replace(".sql", ".tgz")
        if candidate.is_file():
            tar_path = candidate
    if tar_path and tar_path.is_file() and tar_path.stat().st_size > 0:
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                _safe_extract_tar(tar, ROOT)
            uploads_ok = (ROOT / "uploads").exists()
            uploads_note = str(tar_path)
        except Exception as exc:
            uploads_ok = False
            uploads_note = f"extract_failed:{exc}"
    elif tar_path and tar_path.is_file():
        uploads_note = "empty_placeholder"

    payload = {
        "action": "restore",
        "status": "ok" if (ok and uploads_ok) else "error",
        "path": str(path),
        "uploads": uploads_note,
        "stderr": (proc.stderr or "")[:500],
    }
    _write_log("restore", payload)
    print("restore", payload["status"], "uploads=", uploads_note)
    return 0 if (ok and uploads_ok) else 1


def cmd_upgrade(revision: str) -> int:
    proc = _run([sys.executable, "-m", "alembic", "upgrade", revision])
    payload = {
        "action": "upgrade",
        "revision": revision,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
    }
    path = _write_log("upgrade", payload)
    print(f"upgrade rc={proc.returncode} log={path}")
    return proc.returncode


def cmd_rollback(steps: int) -> int:
    target = f"-{steps}"
    proc = _run([sys.executable, "-m", "alembic", "downgrade", target])
    payload = {
        "action": "rollback",
        "steps": steps,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
    }
    path = _write_log("rollback", payload)
    print(f"rollback rc={proc.returncode} log={path}")
    return proc.returncode


def _profile_env(profile: str) -> dict:
    """Merge DeploymentConfig.env_vars into process env for compose up."""
    env = os.environ.copy()
    try:
        from app.services.deployment import DeploymentProfile, PROFILES
        cfg = PROFILES[DeploymentProfile(profile)]
        env.update(cfg.env_vars)
    except Exception:
        if profile in ("standard", "enterprise"):
            env.setdefault("RAGFLOW_ENABLED", "true")
            env.setdefault("PIPESHUB_ENABLED", "true")
            env.setdefault("WEKNORA_ENABLED", "true")
        else:
            env.setdefault("RAGFLOW_ENABLED", "false")
            env.setdefault("PIPESHUB_ENABLED", "false")
            env.setdefault("WEKNORA_ENABLED", "false")
    env.setdefault("RAGFLOW_BASE_URL", "http://ragflow:9380")
    env.setdefault("PIPESHUB_BASE_URL", "http://pipeshub-api:3000")
    env.setdefault("WEKNORA_BASE_URL", "http://weknora:8080")
    env.setdefault("PIPESHUB_ALLOW_MOCK", "false")
    return env


def cmd_install(profile: str) -> int:
    pf = cmd_preflight(profile)
    if pf != 0:
        print("install aborted: preflight failed")
        return pf
    env = _profile_env(profile)
    print(f"install profile={profile} packs="
          f"ragflow={env.get('RAGFLOW_ENABLED')} "
          f"pipeshub={env.get('PIPESHUB_ENABLED')} "
          f"weknora={env.get('WEKNORA_ENABLED')}")
    proc = subprocess.run(
        [
            "docker", "compose", "-f", str(COMPOSE_FILE),
            "--profile", profile, "up", "-d",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    # migrations
    mig = _run([sys.executable, "-m", "alembic", "upgrade", "head"])
    payload = {
        "action": "install",
        "profile": profile,
        "env_packs": {
            "RAGFLOW_ENABLED": env.get("RAGFLOW_ENABLED"),
            "PIPESHUB_ENABLED": env.get("PIPESHUB_ENABLED"),
            "WEKNORA_ENABLED": env.get("WEKNORA_ENABLED"),
        },
        "compose_rc": proc.returncode,
        "migrate_rc": mig.returncode,
        "compose_err": (proc.stderr or "")[-1000:],
        "migrate_err": (mig.stderr or "")[-1000:],
    }
    path = _write_log("install", payload)
    ok = proc.returncode == 0 and mig.returncode == 0
    print(f"install ok={ok} log={path}")
    return 0 if ok else 1


def cmd_remove(profile: str, volumes: bool) -> int:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", profile, "down"]
    if volumes:
        cmd.append("-v")
    proc = _run(cmd)
    payload = {
        "action": "remove",
        "profile": profile,
        "volumes": volumes,
        "returncode": proc.returncode,
        "stderr": (proc.stderr or "")[-1000:],
    }
    path = _write_log("remove", payload)
    print(f"remove rc={proc.returncode} log={path}")
    return proc.returncode


def cmd_status(profile: str) -> int:
    proc = _run([
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "--profile", profile, "ps",
    ])
    print(proc.stdout or proc.stderr)
    _write_log("status", {
        "action": "status",
        "profile": profile,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:4000],
    })
    return proc.returncode


def main() -> int:
    p = argparse.ArgumentParser(description="Enclave ops lifecycle")
    p.add_argument("action", choices=[
        "preflight", "backup", "restore", "upgrade", "rollback", "install", "remove", "status",
    ])
    p.add_argument("--profile", default="lite")
    p.add_argument("--revision", default="head")
    p.add_argument("--steps", type=int, default=1)
    p.add_argument("--volumes", action="store_true")
    p.add_argument("--sql", default="", help="SQL dump path for restore")
    p.add_argument("--uploads-tar", default="", help="Optional uploads_*.tgz for restore")
    args = p.parse_args()

    if args.action == "preflight":
        return cmd_preflight(args.profile)
    if args.action == "backup":
        return cmd_backup()
    if args.action == "restore":
        if not args.sql:
            print("--sql required for restore")
            return 2
        return cmd_restore(args.sql, uploads_tar=args.uploads_tar)
    if args.action == "upgrade":
        return cmd_upgrade(args.revision)
    if args.action == "rollback":
        return cmd_rollback(args.steps)
    if args.action == "install":
        return cmd_install(args.profile)
    if args.action == "remove":
        return cmd_remove(args.profile, args.volumes)
    if args.action == "status":
        return cmd_status(args.profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
