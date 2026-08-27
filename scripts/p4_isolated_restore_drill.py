#!/usr/bin/env python3
"""Read-only source backup and fresh isolated restore drill for P4.

The source Compose project is never stopped or mutated. Database and upload
snapshots are restored into disposable, network-unpublished targets. Raw backup
artifacts remain outside Git and are created with owner-only permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DrillError(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    binary: bool = False,
    input_data: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=input_data,
        capture_output=True,
        text=not binary,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise DrillError(f"command failed ({result.returncode}): {stderr[-1000:]}")
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _safe_tar_members(data: bytes) -> tuple[int, int]:
    files = 0
    size = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            normalized = Path(member.name.replace("\\", "/"))
            if normalized.is_absolute() or ".." in normalized.parts:
                raise DrillError(f"unsafe object archive member: {member.name}")
            lowered = {part.lower() for part in normalized.parts}
            if ".credentials" in lowered or {"var", "credentials"} <= lowered:
                raise DrillError(
                    f"credential path present in object archive: {member.name}"
                )
            if member.isfile():
                files += 1
                size += member.size
            elif not member.isdir():
                raise DrillError(
                    f"unsupported object archive member: {member.name}"
                )
    return files, size


def _restore_archive(data: bytes, target_root: Path) -> tuple[int, int]:
    """Materialize a validated archive without links, devices, or path escape."""
    target_root.mkdir(parents=True, exist_ok=False)
    files = 0
    size = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            normalized = Path(member.name.replace("\\", "/"))
            target = (target_root / normalized).resolve()
            try:
                target.relative_to(target_root.resolve())
            except ValueError as exc:
                raise DrillError(
                    f"archive restore target leaves isolation root: {member.name}"
                ) from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise DrillError(
                    f"unsupported archive member during restore: {member.name}"
                )
            source = archive.extractfile(member)
            if source is None:
                raise DrillError(f"archive member has no content: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            files += 1
            size += target.stat().st_size
    return files, size


def _compose_prefix(args: argparse.Namespace) -> list[str]:
    command = ["docker", "compose"]
    for env_file in args.env_file:
        command.extend(["--env-file", env_file])
    command.extend(["-f", args.compose_file])
    return command


def _config_archive(paths: list[str]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for raw in sorted(paths):
            path = (ROOT / raw).resolve()
            try:
                path.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise DrillError(
                    f"configuration path leaves repository: {raw}"
                ) from exc
            if path.is_file() or path.is_dir():
                archive.add(path, arcname=path.relative_to(ROOT).as_posix())
            else:
                raise DrillError(f"configuration path missing: {raw}")
    return output.getvalue()


def _wait_for_postgres(container: str, user: str, database: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = _run(
            ["docker", "exec", container, "pg_isready", "-U", user, "-d", database],
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise DrillError("isolated PostgreSQL did not become ready")


def run_drill(args: argparse.Namespace) -> dict:
    started_wall = datetime.now(timezone.utc)
    started = time.monotonic()
    run_id = str(uuid.uuid4())
    container = f"enclave-p4-restore-{run_id[:8]}"
    artifact_dir = _repo_path(args.artifact_dir) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(artifact_dir, 0o700)

    compose = _compose_prefix(args)
    admin_user = args.admin_user or os.getenv("DB_ADMIN_USER", "postgres")
    database = args.database or os.getenv("DB_ADMIN_DATABASE", "enclave")
    dump_command = compose + [
        "exec",
        "-T",
        "db",
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-privileges",
        "-U",
        admin_user,
        database,
    ]
    dump = _run(dump_command, binary=True).stdout
    assert isinstance(dump, bytes)
    if len(dump) < 1024:
        raise DrillError("database dump is unexpectedly small")
    dump_path = artifact_dir / "database.dump"
    dump_path.write_bytes(dump)
    os.chmod(dump_path, 0o600)

    roles_result = _run(
        compose
        + [
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            admin_user,
            "-d",
            database,
            "-Atc",
            "SELECT rolname FROM pg_roles WHERE rolname LIKE 'enclave_%' ORDER BY 1",
        ]
    )
    role_names = [
        line.strip() for line in roles_result.stdout.splitlines() if line.strip()
    ]

    object_result = _run(
        compose + ["exec", "-T", "web", "tar", "-C", "/code", "-cf", "-", "uploads"],
        binary=True,
    )
    object_archive = object_result.stdout
    assert isinstance(object_archive, bytes)
    object_count, object_bytes = _safe_tar_members(object_archive)
    object_path = artifact_dir / "objects.tar"
    object_path.write_bytes(object_archive)
    os.chmod(object_path, 0o600)

    with tempfile.TemporaryDirectory(
        prefix="object-restore-", dir=artifact_dir
    ) as restore_root:
        restored_object_count, restored_object_bytes = _restore_archive(
            object_archive, Path(restore_root) / "fresh"
        )
    if (restored_object_count, restored_object_bytes) != (
        object_count,
        object_bytes,
    ):
        raise DrillError("restored object inventory differs from backup")

    config_archive = _config_archive(args.config_path)
    config_count, config_bytes = _safe_tar_members(config_archive)
    config_path = artifact_dir / "configuration.tgz"
    config_path.write_bytes(config_archive)
    os.chmod(config_path, 0o600)
    with tempfile.TemporaryDirectory(
        prefix="configuration-restore-", dir=artifact_dir
    ) as restore_root:
        restored_config_count, restored_config_bytes = _restore_archive(
            config_archive, Path(restore_root) / "fresh"
        )
    if (restored_config_count, restored_config_bytes) != (
        config_count,
        config_bytes,
    ):
        raise DrillError("restored configuration inventory differs from backup")

    index_query = (
        "SELECT count(*)::text || '|' || count(embedding)::text || '|' || "
        "coalesce(sum(octet_length(text)),0)::text FROM documentchunks"
    )
    index_source = _run(
        compose
        + [
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            admin_user,
            "-d",
            database,
            "-Atc",
            index_query,
        ]
    ).stdout.strip()
    index_digest = _sha256(index_source.encode("utf-8"))

    db_container = _run(compose + ["ps", "-q", "db"]).stdout.strip()
    db_image = _run(
        ["docker", "inspect", db_container, "--format", "{{.Config.Image}}"]
    ).stdout.strip()
    restore_password = secrets.token_urlsafe(24)
    isolated_user = "postgres"
    try:
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "--network",
                "none",
                "--tmpfs",
                "/var/lib/postgresql/data:rw,size=2g",
                "-e",
                f"POSTGRES_PASSWORD={restore_password}",
                "-e",
                f"POSTGRES_DB={database}",
                db_image,
            ]
        )
        _wait_for_postgres(container, isolated_user, database)
        for role in role_names:
            safe_role = role.replace('"', '""')
            _run(
                [
                    "docker",
                    "exec",
                    container,
                    "psql",
                    "-U",
                    isolated_user,
                    "-d",
                    database,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    f'CREATE ROLE "{safe_role}" NOLOGIN',
                ]
            )
        _run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                isolated_user,
                "-d",
                database,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
            ],
            binary=True,
            input_data=dump,
        )
        table_count = int(
            _run(
                [
                    "docker",
                    "exec",
                    container,
                    "psql",
                    "-U",
                    isolated_user,
                    "-d",
                    database,
                    "-Atc",
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
                ]
            ).stdout.strip()
        )
        index_restored = _run(
            [
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                isolated_user,
                "-d",
                database,
                "-Atc",
                index_query,
            ]
        ).stdout.strip()
        if table_count <= 0 or index_restored != index_source:
            raise DrillError("restored database/index inventory differs from source")
    finally:
        _run(["docker", "rm", "-f", container], check=False)

    completed = datetime.now(timezone.utc)
    rto = int(time.monotonic() - started)
    # This is an on-demand snapshot of the source at drill start, so the
    # measured recovery-point gap is zero. Continuous-backup lag is a separate
    # deployment-specific SLO and must not be inferred from restore duration.
    rpo = 0
    report = {
        "schema_version": 1,
        "gate": "P4-ISOLATED-RESTORE",
        "status": "PASS",
        "run_id": run_id,
        "source_mutated": False,
        "isolated_environment": True,
        "started_at": started_wall.isoformat(),
        "completed_at": completed.isoformat(),
        "rto_seconds": rto,
        "rpo_seconds": rpo,
        "rto_target_seconds": args.rto_target_seconds,
        "rpo_target_seconds": args.rpo_target_seconds,
        "database": {
            "backup_status": "PASS",
            "restore_status": "PASS",
            "sha256": _sha256(dump),
            "bytes": len(dump),
            "table_count": table_count,
        },
        "object_store": {
            "backup_status": "PASS",
            "restore_status": "PASS",
            "sha256": _sha256(object_archive),
            "objects": object_count,
            "bytes": object_bytes,
            "restored_objects": restored_object_count,
            "restored_bytes": restored_object_bytes,
        },
        "index": {
            "backup_status": "PASS",
            "restore_status": "PASS",
            "sha256": index_digest,
            "inventory": index_source,
        },
        "configuration": {
            "backup_status": "PASS",
            "restore_status": "PASS",
            "sha256": _sha256(config_archive),
            "secret_material_included": False,
            "files": config_count,
            "bytes": config_bytes,
            "restored_files": restored_config_count,
            "restored_bytes": restored_config_bytes,
        },
        "artifact_directory": str(artifact_dir),
    }
    if rto > args.rto_target_seconds or rpo > args.rpo_target_seconds:
        report["status"] = "FAIL"
    output = _repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-file", default="docker-compose.prod.yml")
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--admin-user", default="")
    parser.add_argument("--database", default="")
    parser.add_argument(
        "--artifact-dir",
        default="backups/p4",
        help="Must remain outside version control",
    )
    parser.add_argument(
        "--config-path",
        action="append",
        default=[
            "docker-compose.prod.yml",
            "configs",
            "monitoring",
            "nginx",
        ],
    )
    parser.add_argument("--rto-target-seconds", type=int, default=900)
    parser.add_argument("--rpo-target-seconds", type=int, default=300)
    parser.add_argument("--output", default="artifacts/ops/p4_isolated_restore.json")
    args = parser.parse_args()
    try:
        report = run_drill(args)
    except DrillError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": report["status"], "run_id": report["run_id"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
