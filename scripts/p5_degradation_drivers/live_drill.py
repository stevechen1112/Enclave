#!/usr/bin/env python3
"""Trusted live driver for the four P5 degradation contracts.

The outer runner executes this file once per lifecycle step. State is persisted
without credentials so recovery can still run after a failed injection/probe.
All Docker mutations are restricted to containers carrying the requested
Compose project/service labels.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCENARIOS = {
    "provider_slow",
    "quota_exhausted",
    "queue_saturated",
    "sidecar_unavailable",
}
STEPS = {"baseline", "inject", "probe", "recover", "verify"}
SIDECAR_DOMAINS = {
    "ragflow": ("ragflow",),
    "pipeshub": ("connector",),
    "weknora": ("wiki", "graph"),
}


class DrillError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run(argv: list[str], *, timeout: int = 60, stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DrillError(f"command failed to execute: {argv[0]}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()
        raise DrillError(f"{argv[0]} exited {result.returncode}: {message[:500]}")
    return result.stdout.strip()


def _container(project: str, service: str) -> str:
    output = _run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ]
    )
    rows = [row.strip() for row in output.splitlines() if row.strip()]
    if len(rows) != 1:
        raise DrillError(
            f"expected exactly one {project}/{service} container, found {len(rows)}"
        )
    return rows[0]


def _container_state(container: str) -> dict[str, Any]:
    raw = _run(["docker", "inspect", container, "--format", "{{json .State}}"])
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise DrillError("container state is not an object")
    return value


def _pause(container: str) -> None:
    state = _container_state(container)
    if state.get("Running") is not True:
        raise DrillError("target container is not running")
    if state.get("Paused") is not True:
        _run(["docker", "pause", container])


def _unpause(container: str) -> None:
    if _container_state(container).get("Paused") is True:
        _run(["docker", "unpause", container])


def _container_python(container: str, source: str, *, timeout: int = 60) -> dict:
    output = _run(
        ["docker", "exec", "-i", container, "python", "-"],
        timeout=timeout,
        stdin=source,
    )
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DrillError("container probe did not return JSON") from exc
    if not isinstance(value, dict):
        raise DrillError("container probe result is not an object")
    return value


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DrillError("drill state does not exist; run baseline first")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DrillError("drill state must be an object")
    return value


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _login(client: httpx.Client, email: str, tenant_id: str) -> dict[str, str]:
    password = os.getenv("P5_ADMIN_PASSWORD", "")
    if not password:
        raise DrillError("P5_ADMIN_PASSWORD must be injected through the environment")
    response = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": email, "password": password},
    )
    response.raise_for_status()
    token = str(_payload(response).get("access_token") or "")
    if not token:
        raise DrillError("login did not return an access token")
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/users/me", headers=headers)
    me.raise_for_status()
    if str(_payload(me).get("tenant_id") or "") != tenant_id:
        raise DrillError("authenticated user does not belong to the drill tenant")
    return headers


def _assert_release(client: httpx.Client, source_commit: str) -> dict[str, Any]:
    response = client.get("/health")
    response.raise_for_status()
    payload = _payload(response)
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    if payload.get("env") != "staging":
        raise DrillError("degradation drill target is not staging")
    if release.get("source_commit") != source_commit:
        raise DrillError("runtime release does not match the plan source_commit")
    if release.get("identifiable") is not True:
        raise DrillError("runtime release identity is incomplete")
    return release


def _upload_asset(
    client: httpx.Client,
    headers: dict[str, str],
    fixture: Path,
    title: str,
) -> tuple[httpx.Response, dict[str, Any]]:
    media_type = mimetypes.guess_type(fixture.name)[0] or "application/octet-stream"
    with fixture.open("rb") as stream:
        response = client.post(
            "/api/v1/knowledge/assets",
            files={"file": (fixture.name, stream, media_type)},
            data={"title": title, "idempotency_key": f"p5-degradation:{uuid.uuid4()}"},
            headers=headers,
        )
    return response, _payload(response)


def _asset_status(
    client: httpx.Client, headers: dict[str, str], asset_id: str
) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/knowledge/assets/{asset_id}/status", headers=headers
    )
    response.raise_for_status()
    return _payload(response)


def _wait_asset_ready(
    client: httpx.Client,
    headers: dict[str, str],
    asset_id: str,
    *,
    timeout: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _asset_status(client, headers, asset_id)
        job = latest.get("job") if isinstance(latest.get("job"), dict) else {}
        status = str(latest.get("status") or "")
        job_status = str(job.get("status") or "")
        if status in {"ready", "active"} and job_status in {"", "ready"}:
            return latest
        if status in {"failed", "cancelled"} or job_status in {
            "failed",
            "cancelled",
        }:
            raise DrillError(f"asset ingestion reached terminal failure: {latest}")
        time.sleep(2)
    raise DrillError(f"asset did not become ready before timeout: {latest}")


def _search_grounded(
    client: httpx.Client, headers: dict[str, str], marker: str
) -> int:
    response = client.post(
        "/api/v1/kb/search",
        json={"query": marker, "top_k": 3, "granularity": "auto"},
        headers=headers,
    )
    response.raise_for_status()
    payload = _payload(response)
    rows = payload.get("results")
    if not isinstance(rows, list) or not rows:
        raise DrillError("canonical grounded search returned no results")
    return len(rows)


def _queue_snapshot(web_container: str) -> dict[str, Any]:
    return _container_python(
        web_container,
        """import json
from redis import Redis
from app.config import settings
from app.services.queue_guardrails import _profile_name, _queue_limit
r=Redis.from_url(settings.CELERY_BROKER_URL)
print(json.dumps({'depth':int(r.llen('celery') or 0),'limit':_queue_limit(_profile_name())}))
r.close()
""",
    )


def _queue_fill(web_container: str, marker: str, count: int) -> dict[str, Any]:
    source = f"""import json
from redis import Redis
from app.config import settings
r=Redis.from_url(settings.CELERY_BROKER_URL)
marker={marker!r}
count={count}
for _ in range(count): r.rpush('celery', marker)
print(json.dumps({{'depth':int(r.llen('celery') or 0),'inserted':count}}))
r.close()
"""
    return _container_python(web_container, source)


def _queue_remove(web_container: str, marker: str) -> dict[str, Any]:
    source = f"""import json
from redis import Redis
from app.config import settings
r=Redis.from_url(settings.CELERY_BROKER_URL)
removed=int(r.lrem('celery', 0, {marker!r}) or 0)
print(json.dumps({{'depth':int(r.llen('celery') or 0),'removed':removed}}))
r.close()
"""
    return _container_python(web_container, source)


def _gateway_health(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/v1/gateway/health", headers=headers)
    response.raise_for_status()
    return _payload(response)


def _sidecar_unavailable(report: dict[str, Any], key: str) -> bool:
    domains = SIDECAR_DOMAINS[key]
    adapters = report.get("adapters") if isinstance(report.get("adapters"), dict) else {}
    return all(
        (adapters.get(domain) or {}).get("status") != "healthy" for domain in domains
    )


def _run_integrity(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    container = _container(args.compose_project, args.integrity_service)
    suffix = uuid.uuid4().hex
    remote = {
        "script": f"/tmp/p5-integrity-{suffix}.py",
        "credentials": f"/tmp/p5-credentials-{suffix}.json",
        "grounding": f"/tmp/p5-grounding-{suffix}.json",
        "output": f"/tmp/p5-integrity-{suffix}.json",
    }
    local_output = args.state_file.with_suffix(f".{suffix}.integrity.json")
    try:
        for source, target in (
            (args.integrity_script, remote["script"]),
            (args.credentials, remote["credentials"]),
            (args.grounding_evidence, remote["grounding"]),
        ):
            _run(["docker", "cp", str(source), f"{container}:{target}"])
        _run(
            [
                "docker",
                "exec",
                container,
                "python",
                remote["script"],
                "--base-url",
                "http://web:8000",
                "--credentials",
                remote["credentials"],
                "--grounding-evidence",
                remote["grounding"],
                "--output",
                remote["output"],
                "--run-started-at",
                state["run_started_at"],
                "--load-completed-at",
                state["load_completed_at"],
                "--reconciliation-timeout-seconds",
                str(args.recovery_timeout_seconds),
                "--poll-seconds",
                "2",
                "--confirm-isolated-staging",
            ],
            timeout=args.recovery_timeout_seconds + 60,
        )
        _run(["docker", "cp", f"{container}:{remote['output']}", str(local_output)])
        value = json.loads(local_output.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DrillError("integrity result is not an object")
        return value
    finally:
        try:
            _run(
                [
                    "docker",
                    "exec",
                    container,
                    "rm",
                    "-f",
                    *remote.values(),
                ]
            )
        except DrillError:
            pass
        if local_output.exists():
            local_output.unlink()


def _baseline(args: argparse.Namespace) -> dict[str, Any]:
    if args.state_file.exists():
        previous = _read_state(args.state_file)
        if previous.get("stage") not in {"verified", "failed"}:
            raise DrillError("unfinished drill state exists; recover it before restarting")
    grounding = json.loads(args.grounding_evidence.read_text(encoding="utf-8"))
    marker = str(grounding.get("marker") or "")
    if grounding.get("source_commit") != args.source_commit or not marker:
        raise DrillError("grounding evidence does not match the drill release")
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
        release = _assert_release(client, args.source_commit)
        headers = _login(client, args.email, args.tenant_id)
        search_results = _search_grounded(client, headers, marker)
        run_started_at = _now()
        response, asset = _upload_asset(
            client,
            headers,
            args.fixture,
            f"P5 degradation control {args.scenario} {uuid.uuid4().hex[:8]}",
        )
        if response.status_code != 202:
            raise DrillError(f"control ingestion was not accepted: {response.status_code}")
        asset_id = str(asset.get("id") or asset.get("asset_id") or "")
        if not asset_id:
            raise DrillError("control ingestion did not return an asset id")
        _wait_asset_ready(
            client,
            headers,
            asset_id,
            timeout=args.recovery_timeout_seconds,
        )
        state: dict[str, Any] = {
            "schema_version": 1,
            "scenario": args.scenario,
            "source_commit": args.source_commit,
            "compose_project": args.compose_project,
            "tenant_id": args.tenant_id,
            "marker": marker,
            "run_started_at": run_started_at,
            "release_id": release.get("release_id"),
            "control_asset_id": asset_id,
            "baseline_search_results": search_results,
            "stage": "baseline",
            "observations": ["release_identified", "tenant_authenticated", "control_ingestion_ready"],
        }
        if args.scenario == "quota_exhausted":
            quota = client.get(
                f"/api/v1/admin/tenants/{args.tenant_id}/quota", headers=headers
            )
            quota.raise_for_status()
            state["original_quota"] = _payload(quota)
        elif args.scenario == "queue_saturated":
            web = _container(args.compose_project, "web")
            state["baseline_queue"] = _queue_snapshot(web)
            if int(state["baseline_queue"].get("depth", -1)) != 0:
                raise DrillError("queue drill requires an empty isolated queue")
        elif args.scenario == "provider_slow":
            provider = _container(args.compose_project, args.provider_service)
            if _container_state(provider).get("Paused") is True:
                raise DrillError("provider container is already paused")
        elif args.scenario == "sidecar_unavailable":
            _container(args.compose_project, args.sidecar_service)
            health = _gateway_health(client, headers)
            if _sidecar_unavailable(health, args.sidecar_key):
                raise DrillError("selected sidecar is not healthy before injection")
    _write_state(args.state_file, state)
    return {"status": "PASS", "step": "baseline", "asset_id": asset_id}


def _inject(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("stage") != "baseline":
        raise DrillError("inject requires baseline state")
    if args.scenario == "quota_exhausted":
        original = state["original_quota"]
        current = float(original.get("current_monthly_cost_usd", 0) or 0)
        temporary = current + 0.000001
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
            headers = _login(client, args.email, args.tenant_id)
            response = client.put(
                f"/api/v1/admin/tenants/{args.tenant_id}/quota",
                json={
                    "monthly_query_limit": None,
                    "monthly_token_limit": None,
                    "monthly_cost_limit_usd": temporary,
                },
                headers=headers,
            )
            response.raise_for_status()
        state["temporary_cost_limit_usd"] = temporary
    elif args.scenario == "queue_saturated":
        web = _container(args.compose_project, "web")
        worker = _container(args.compose_project, "worker")
        snapshot = _queue_snapshot(web)
        count = int(snapshot["limit"]) - int(snapshot["depth"])
        if count <= 0:
            raise DrillError("queue was already saturated before marker injection")
        marker = f"p5-degradation-marker:{uuid.uuid4()}"
        # Journal the exact recovery selector before mutating Redis. The outer
        # runner can now recover safely even if this process dies mid-fill.
        state.update({"queue_marker": marker, "queue_markers_planned": count})
        state["stage"] = "injecting"
        _write_state(args.state_file, state)
        _pause(worker)
        filled = _queue_fill(web, marker, count)
        if int(filled.get("depth", -1)) < int(snapshot["limit"]):
            raise DrillError("queue marker injection did not reach the guard limit")
        state["queue_markers_inserted"] = int(filled.get("inserted", count))
    elif args.scenario == "provider_slow":
        provider = _container(args.compose_project, args.provider_service)
        _pause(provider)
        state["provider_container"] = provider
    else:
        sidecar = _container(args.compose_project, args.sidecar_service)
        _pause(sidecar)
        state["sidecar_container"] = sidecar
    state["stage"] = "injected"
    state["injected_at"] = _now()
    state["observations"].append("fault_injected")
    _write_state(args.state_file, state)
    return {"status": "PASS", "step": "inject"}


def _probe(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("stage") != "injected":
        raise DrillError("probe requires injected state")
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
        headers = _login(client, args.email, args.tenant_id)
        if args.scenario == "quota_exhausted":
            response = client.post(
                "/api/v1/chat/chat",
                json={"question": "P5 quota degradation probe", "top_k": 1},
                headers=headers,
            )
            detail = _payload(response).get("detail", _payload(response))
            if not (
                response.status_code == 429
                and isinstance(detail, dict)
                and detail.get("axis") == "cost"
            ):
                raise DrillError("quota exhaustion did not return a cost-axis 429")
            observation = {"status_code": 429, "axis": "cost"}
        elif args.scenario == "queue_saturated":
            response, payload = _upload_asset(
                client, headers, args.fixture, "P5 rejected saturated queue probe"
            )
            detail = payload.get("detail", payload)
            if not (
                response.status_code == 503
                and isinstance(detail, dict)
                and detail.get("error") == "queue_saturated"
                and int(response.headers.get("Retry-After", "0")) > 0
            ):
                raise DrillError("saturated queue did not reject intake with Retry-After")
            observation = {"status_code": 503, "error": "queue_saturated"}
        elif args.scenario == "provider_slow":
            response, asset = _upload_asset(
                client, headers, args.fixture, "P5 slow provider probe"
            )
            if response.status_code != 202:
                raise DrillError("slow-provider intake was not accepted asynchronously")
            asset_id = str(asset.get("id") or asset.get("asset_id") or "")
            time.sleep(args.degraded_observation_seconds)
            status = _asset_status(client, headers, asset_id)
            job = status.get("job") if isinstance(status.get("job"), dict) else {}
            if status.get("status") in {"ready", "active"} or job.get("status") == "ready":
                raise DrillError("provider-slow work was falsely reported ready")
            state["probe_asset_id"] = asset_id
            observation = {"asset_id": asset_id, "degraded_status": status}
        else:
            report = _gateway_health(client, headers)
            if not _sidecar_unavailable(report, args.sidecar_key):
                raise DrillError("gateway did not expose the unavailable sidecar")
            results = _search_grounded(client, headers, state["marker"])
            observation = {"gateway": report.get("gateway"), "core_search_results": results}
    state["stage"] = "probed"
    state["degraded_observation"] = observation
    state["observations"].append("degraded_contract_observed")
    _write_state(args.state_file, state)
    return {"status": "PASS", "step": "probe", "observation": observation}


def _recover(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        if args.scenario == "quota_exhausted" and state.get("original_quota"):
            original = state["original_quota"]
            with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
                headers = _login(client, args.email, args.tenant_id)
                response = client.put(
                    f"/api/v1/admin/tenants/{args.tenant_id}/quota",
                    json={
                        "monthly_query_limit": original.get("monthly_query_limit"),
                        "monthly_token_limit": original.get("monthly_token_limit"),
                        "monthly_cost_limit_usd": original.get("monthly_cost_limit_usd"),
                    },
                    headers=headers,
                )
                response.raise_for_status()
        elif args.scenario == "queue_saturated":
            web = _container(args.compose_project, "web")
            if state.get("queue_marker"):
                removed = _queue_remove(web, str(state["queue_marker"]))
                inserted = state.get("queue_markers_inserted")
                if inserted is not None and int(removed.get("removed", -1)) != int(
                    inserted
                ):
                    errors.append("not all queue markers were removed")
                baseline_depth = int(
                    (state.get("baseline_queue") or {}).get("depth", 0)
                )
                if int(removed.get("depth", -1)) != baseline_depth:
                    errors.append("queue did not return to its pre-injection depth")
            _unpause(_container(args.compose_project, "worker"))
        elif args.scenario == "provider_slow":
            _unpause(_container(args.compose_project, args.provider_service))
        elif args.scenario == "sidecar_unavailable":
            _unpause(_container(args.compose_project, args.sidecar_service))
    except (DrillError, httpx.HTTPError) as exc:
        errors.append(str(exc))
    state["stage"] = "recovered" if not errors else "recovery_failed"
    state["recovered_at"] = _now()
    if not errors:
        state["observations"].append("fault_recovered")
    else:
        state["recovery_errors"] = errors
    _write_state(args.state_file, state)
    if errors:
        raise DrillError("; ".join(errors))
    return {"status": "PASS", "step": "recover"}


def _verify(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("stage") != "recovered":
        raise DrillError("verify requires recovered state")
    scenario_observation: dict[str, Any]
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
        _assert_release(client, args.source_commit)
        headers = _login(client, args.email, args.tenant_id)
        if args.scenario == "quota_exhausted":
            quota = client.get(
                f"/api/v1/admin/tenants/{args.tenant_id}/quota", headers=headers
            )
            quota.raise_for_status()
            current = _payload(quota)
            original = state["original_quota"]
            restored = all(
                current.get(field) == original.get(field)
                for field in (
                    "monthly_query_limit",
                    "monthly_token_limit",
                    "monthly_cost_limit_usd",
                )
            )
            if not restored:
                raise DrillError("tenant quota was not restored exactly")
            scenario_observation = {"quota_restored": True}
        elif args.scenario == "queue_saturated":
            web = _container(args.compose_project, "web")
            snapshot = _queue_snapshot(web)
            if int(snapshot.get("depth", -1)) != 0:
                raise DrillError("queue did not return to its empty baseline")
            response, asset = _upload_asset(
                client, headers, args.fixture, "P5 queue recovery control"
            )
            if response.status_code != 202:
                raise DrillError("queue did not accept work after recovery")
            asset_id = str(asset.get("id") or asset.get("asset_id") or "")
            _wait_asset_ready(
                client,
                headers,
                asset_id,
                timeout=args.recovery_timeout_seconds,
            )
            scenario_observation = {"queue_depth": 0, "recovery_asset_id": asset_id}
        elif args.scenario == "provider_slow":
            asset_id = str(state.get("probe_asset_id") or "")
            ready = _wait_asset_ready(
                client,
                headers,
                asset_id,
                timeout=args.recovery_timeout_seconds,
            )
            scenario_observation = {"recovered_asset_id": asset_id, "status": ready}
        else:
            deadline = time.monotonic() + args.recovery_timeout_seconds
            report: dict[str, Any] = {}
            while time.monotonic() < deadline:
                report = _gateway_health(client, headers)
                if not _sidecar_unavailable(report, args.sidecar_key):
                    break
                time.sleep(5)
            if _sidecar_unavailable(report, args.sidecar_key):
                raise DrillError("sidecar did not recover before timeout")
            results = _search_grounded(client, headers, state["marker"])
            scenario_observation = {"sidecar_recovered": True, "core_search_results": results}
    state["load_completed_at"] = _now()
    _write_state(args.state_file, state)
    integrity = _run_integrity(args, state)
    passed = (
        integrity.get("status") == "PASS"
        and integrity.get("data_corruption") == 0
        and integrity.get("cross_tenant_leak") == 0
        and integrity.get("unrecoverable_backlog") == 0
    )
    result = {
        "schema_version": 1,
        "scenario": args.scenario,
        "source_commit": args.source_commit,
        "tenant_id": args.tenant_id,
        "data_loss": 0 if integrity.get("data_corruption") == 0 else 1,
        "false_completion": 0 if passed else 1,
        "cross_tenant_leak": integrity.get("cross_tenant_leak", -1),
        "recovered": passed,
        "observations": [
            *state.get("observations", []),
            {"degraded": state.get("degraded_observation")},
            {"recovery": scenario_observation},
            {"integrity": integrity.get("observations", {})},
        ],
    }
    state["stage"] = "verified" if passed else "failed"
    state["verification"] = result
    _write_state(args.state_file, state)
    if not passed:
        raise DrillError("post-recovery integrity verification failed")
    return result


def _validate_args(args: argparse.Namespace) -> None:
    if args.scenario not in SCENARIOS or args.step not in STEPS:
        raise DrillError("unsupported scenario or lifecycle step")
    if len(args.source_commit) != 40:
        raise DrillError("source_commit must be a full git SHA")
    required_paths = {
        "baseline": (args.fixture, args.grounding_evidence),
        "inject": (),
        "probe": (args.fixture,),
        "recover": (),
        "verify": (
            args.credentials,
            args.grounding_evidence,
            args.integrity_script,
        ),
    }
    for path in required_paths[args.step]:
        if not path.is_file():
            raise DrillError(f"required file does not exist: {path}")
    if args.sidecar_key not in SIDECAR_DOMAINS:
        raise DrillError("unsupported sidecar key")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p5-scenario", dest="scenario", required=True)
    parser.add_argument("--p5-step", dest="step", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--grounding-evidence", type=Path, required=True)
    parser.add_argument("--integrity-script", type=Path, required=True)
    parser.add_argument("--integrity-service", default="worker")
    parser.add_argument("--provider-service", default="ollama-embed")
    parser.add_argument("--sidecar-key", default="ragflow")
    parser.add_argument("--sidecar-service", default="ragflow")
    parser.add_argument("--degraded-observation-seconds", type=int, default=10)
    parser.add_argument("--recovery-timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    try:
        _validate_args(args)
        if args.step == "baseline":
            result = _baseline(args)
        else:
            state = _read_state(args.state_file)
            if (
                state.get("scenario") != args.scenario
                or state.get("source_commit") != args.source_commit
                or state.get("tenant_id") != args.tenant_id
            ):
                raise DrillError("state binding does not match this plan")
            result = {
                "inject": _inject,
                "probe": _probe,
                "recover": _recover,
                "verify": _verify,
            }[args.step](args, state)
    except (DrillError, OSError, ValueError, json.JSONDecodeError, httpx.HTTPError) as exc:
        print(json.dumps({"status": "FAIL", "step": args.step, "error": str(exc)}))
        return 8
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
