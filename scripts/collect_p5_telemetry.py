#!/usr/bin/env python3
"""Crash-resumable P5 telemetry collector for capacity and soak runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_telemetry import (
    parse_docker_stats,
    parse_prometheus_text,
    summarize_samples,
    telemetry_snapshot,
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _get(url: str, timeout: float = 10) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "enclave-p5-collector"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read().decode(
                "utf-8", errors="replace"
            )
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def _safe_container_name(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if not value or any(char not in allowed for char in value):
        raise ValueError("container name contains unsupported characters")
    return value


def _docker_stats(
    enabled: bool, *, compose_project: str | None
) -> tuple[list[dict], str | None]:
    if not enabled:
        return [], None
    if not compose_project:
        return [], "docker Compose project is required"
    try:
        project = _safe_container_name(compose_project)
        listing = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        names = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
        if listing.returncode != 0:
            return [], listing.stderr.strip() or "docker ps failed"
        if not names:
            return [], f"no running containers found for Compose project {project}"
        result = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                *names,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    if result.returncode != 0:
        return [], result.stderr.strip() or "docker stats failed"
    return parse_docker_stats(result.stdout), None


def _internal_metrics(container: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            _safe_container_name(container),
            "curl",
            "-sSf",
            "http://127.0.0.1:8000/metrics",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "internal metrics request failed")
    return result.stdout


def _gpu_stats(enabled: bool) -> tuple[list[dict], str | None]:
    if not enabled:
        return [], None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    if result.returncode != 0:
        return [], result.stderr.strip() or "nvidia-smi failed"
    rows = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        rows.append(
            {
                "index": int(parts[0]),
                "name": parts[1],
                "utilization_percent": float(parts[2]),
                "memory_used_mb": float(parts[3]),
                "memory_total_mb": float(parts[4]),
            }
        )
    return rows, None


def _read_samples(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append(path: Path, sample: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def collect_once(
    base_url: str,
    *,
    docker_stats: bool,
    gpu_stats: bool,
    metrics_container: str | None = None,
    compose_project: str | None = None,
) -> dict:
    sample = {"captured_at": _iso_now(), "host_cpu_cores": int(os.cpu_count() or 0)}
    try:
        health_status, health_body = _get(base_url.rstrip("/") + "/health")
        sample["health_status"] = health_status
        try:
            sample["health"] = json.loads(health_body)
        except json.JSONDecodeError:
            sample["health"] = {"raw": health_body[:500]}
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        sample["health_status"] = 0
        sample["health_error"] = str(exc)
    try:
        if metrics_container:
            metrics_body = _internal_metrics(metrics_container)
        else:
            metrics_status, metrics_body = _get(base_url.rstrip("/") + "/metrics")
            if metrics_status != 200:
                raise RuntimeError(f"metrics returned HTTP {metrics_status}")
        sample["runtime"] = telemetry_snapshot(parse_prometheus_text(metrics_body))
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        urllib.error.URLError,
        ValueError,
    ) as exc:
        sample["runtime"] = {}
        sample["metrics_error"] = str(exc)
    containers, container_error = _docker_stats(
        docker_stats, compose_project=compose_project
    )
    sample["containers"] = containers
    if container_error:
        sample["container_error"] = container_error
    gpus, gpu_error = _gpu_stats(gpu_stats)
    sample["gpus"] = gpus
    if gpu_error:
        sample["gpu_error"] = gpu_error
    return sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--docker-stats", action="store_true")
    parser.add_argument("--metrics-container")
    parser.add_argument("--compose-project")
    parser.add_argument("--gpu-stats", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0, help="test-only bound")
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.interval_seconds <= 0:
        parser.error("duration and interval must be positive")
    if args.docker_stats and not args.compose_project:
        parser.error("--compose-project is required with --docker-stats")

    existing = _read_samples(args.output)
    if existing:
        started = datetime.fromisoformat(existing[0]["captured_at"])
    else:
        started = datetime.now(UTC)
    samples = existing
    deadline = started + timedelta(seconds=args.duration_seconds)
    while datetime.now(UTC) < deadline:
        next_capture = started + timedelta(
            seconds=len(samples) * args.interval_seconds
        )
        remaining = (next_capture - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            time.sleep(min(remaining, 60))
            continue
        sample = collect_once(
            args.base_url,
            docker_stats=args.docker_stats,
            gpu_stats=args.gpu_stats,
            metrics_container=args.metrics_container,
            compose_project=args.compose_project,
        )
        _append(args.output, sample)
        samples.append(sample)
        summary = {
            "schema_version": 1,
            "status": "RUNNING",
            "started_at": started.isoformat(),
            "last_sample_at": sample["captured_at"],
            "duration_target_seconds": args.duration_seconds,
            **summarize_samples(samples),
        }
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if args.max_samples and len(samples) >= args.max_samples:
            break

    completed = datetime.now(UTC)
    elapsed = int((completed - started).total_seconds())
    status = "PASS" if elapsed >= args.duration_seconds else "INCOMPLETE"
    summary = {
        "schema_version": 1,
        "status": status,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_seconds": elapsed,
        "duration_target_seconds": args.duration_seconds,
        **summarize_samples(samples),
    }
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
