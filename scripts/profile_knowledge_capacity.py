#!/usr/bin/env python3
"""Read-only lexical capacity profile with explicit corpus-size coverage."""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, engine
from app.models.document import DocumentChunk
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
from app.services.lexical_index import search
from app.services.read_only_barrier import process_read_only

DEPLOYMENT_PROFILES = {
    "lite": {"sizes": [1_000, 10_000], "concurrency": 4, "p95_ms": 750, "p99_ms": 1_500, "cpu_peak_percent": 85, "memory_peak_mb": 4_096},
    "team": {"sizes": [1_000, 10_000, 100_000], "concurrency": 16, "p95_ms": 1_000, "p99_ms": 2_000, "cpu_peak_percent": 85, "memory_peak_mb": 16_384},
    "enterprise": {"sizes": [1_000, 10_000, 100_000, 1_000_000], "concurrency": 32, "p95_ms": 1_500, "p99_ms": 3_000, "cpu_peak_percent": 85, "memory_peak_mb": 65_536},
}


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(round((len(ordered) - 1) * fraction), len(ordered) - 1)]


def profile_verdict(metrics: dict, limits: dict, *, baseline_hit_rate: float) -> tuple[str, list[str]]:
    reasons = []
    if metrics.get("error_rate", 1) != 0:
        reasons.append("query_errors_present")
    if metrics.get("scope_violations", 1) != 0:
        reasons.append("tenant_acl_or_revision_scope_violation")
    if (metrics.get("hit_at_10") or 0) < baseline_hit_rate:
        reasons.append("retrieval_quality_below_baseline")
    if (metrics.get("p95_ms") or float("inf")) > limits["p95_ms"]:
        reasons.append("p95_above_profile_limit")
    if (metrics.get("p99_ms") or float("inf")) > limits["p99_ms"]:
        reasons.append("p99_above_profile_limit")
    return ("PASS" if not reasons else "FAIL"), reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument(
        "--queries",
        required=True,
        help="JSON objects: query + expected_chunk_ids; content is never written to output",
    )
    parser.add_argument("--profile", choices=sorted(DEPLOYMENT_PROFILES), default="lite")
    parser.add_argument("--sizes", help="override profile sizes; comma-separated chunks")
    parser.add_argument("--concurrency", type=int, help="override profile concurrency")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--baseline-hit-rate", type=float, default=.90)
    parser.add_argument("--resource-observation", required=True, help="operator JSON with CPU, memory, storage and hourly cost")
    parser.add_argument("--output", default="artifacts/knowledge/capacity_profile_last_run.json")
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", args.image_digest):
        raise SystemExit("image-digest must be sha256:<64 hex>")
    tenant_id = UUID(args.tenant_id); revision_id = UUID(args.revision_id)
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    if (
        not isinstance(queries, list)
        or len(queries) < 20
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("query"), str)
            and item["query"].strip()
            and isinstance(item.get("expected_chunk_ids"), list)
            and item["expected_chunk_ids"]
            for item in queries
        )
    ):
        raise SystemExit("queries must contain >=20 query/expected_chunk_ids objects")
    limits = dict(DEPLOYMENT_PROFILES[args.profile])
    sizes = limits["sizes"] if not args.sizes else sorted(
        {int(value) for value in args.sizes.split(",") if int(value) > 0}
    )
    concurrency = args.concurrency or limits["concurrency"]
    if not set(limits["sizes"]).issubset(sizes):
        raise SystemExit("size override cannot omit a deployment profile's required tiers")
    if concurrency < limits["concurrency"] or args.iterations < 1 or not .90 <= args.baseline_hit_rate <= 1:
        raise SystemExit("invalid concurrency, iterations or baseline hit rate")
    resource_observation = json.loads(Path(args.resource_observation).read_text(encoding="utf-8"))
    required_resource_fields = {
        "image_digest", "deployment_profile", "cpu_peak_percent", "memory_peak_mb",
        "storage_limit_bytes", "infrastructure_hourly_cost", "observer", "attestation_sha256",
    }
    if (
        not isinstance(resource_observation, dict)
        or not required_resource_fields.issubset(resource_observation)
        or resource_observation.get("image_digest") != args.image_digest
        or resource_observation.get("deployment_profile") != args.profile
        or not re.fullmatch(r"[0-9a-fA-F]{64}", str(resource_observation.get("attestation_sha256") or ""))
    ):
        raise SystemExit("resource observation is incomplete or not bound to image/profile")
    db = SessionLocal()
    try:
        revision = db.query(KnowledgeBaseRevision).join(KnowledgeBase).filter(
            KnowledgeBaseRevision.id == revision_id,
            KnowledgeBase.tenant_id == tenant_id,
        ).first()
        if revision is None:
            raise SystemExit("revision not found for tenant")
        manifest_hash = revision.manifest_hash
        available = db.query(func.count(DocumentChunk.id)).join(
            KnowledgeBaseRevisionDocument,
            (KnowledgeBaseRevisionDocument.document_id == DocumentChunk.document_id)
            & (KnowledgeBaseRevisionDocument.document_revision == DocumentChunk.document_revision),
        ).filter(
            KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
            KnowledgeBaseRevisionDocument.kb_revision_id == revision_id,
        ).scalar() or 0
        index_bytes = int(db.execute(text("SELECT pg_total_relation_size('knowledge_lexical_index')")).scalar() or 0)
    finally:
        db.close()

    profiles = []
    with process_read_only(engine):
        for size in sizes:
            if available < size:
                profiles.append({"chunks": size, "status": "BLOCKED", "reason": "insufficient_corpus", "available_chunks": available})
                continue
            def execute(spec: dict, sample_size: int = size):
                session = SessionLocal()
                try:
                    sampled_chunks = session.query(DocumentChunk.id.label("chunk_id")).join(
                        KnowledgeBaseRevisionDocument,
                        (KnowledgeBaseRevisionDocument.document_id == DocumentChunk.document_id)
                        & (KnowledgeBaseRevisionDocument.document_revision == DocumentChunk.document_revision),
                    ).filter(
                        KnowledgeBaseRevisionDocument.tenant_id == tenant_id,
                        KnowledgeBaseRevisionDocument.kb_revision_id == revision_id,
                    ).order_by(DocumentChunk.id).limit(sample_size).subquery()
                    base = session.query(DocumentChunk).join(
                        sampled_chunks, sampled_chunks.c.chunk_id == DocumentChunk.id,
                    )
                    started = time.perf_counter()
                    results = search(
                        session,
                        tenant_id=tenant_id,
                        query=spec["query"],
                        top_k=10,
                        base_query=base,
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    result_ids = {str(chunk.id) for chunk, _score in results}
                    expected = {str(value) for value in spec["expected_chunk_ids"]}
                    hit = bool(result_ids.intersection(expected))
                    scope_violations = sum(
                        1 for chunk, _score in results
                        if chunk.tenant_id != tenant_id
                    )
                    return elapsed, hit, scope_violations, None
                except Exception as exc:  # noqa: BLE001 - gate records type and fail-closes
                    return 0.0, False, 0, type(exc).__name__
                finally:
                    session.close()

            jobs = [spec for spec in queries for _ in range(args.iterations)]
            started_batch = time.perf_counter()
            results = []
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(execute, spec) for spec in jobs]
                for future in as_completed(futures):
                    results.append(future.result())
            batch_seconds = max(time.perf_counter() - started_batch, .000001)
            timings = [elapsed for elapsed, _hit, _scope, error in results if error is None]
            errors = [error for _elapsed, _hit, _scope, error in results if error]
            # Each query is repeated for latency; quality denominator remains the
            # complete run and is therefore conservative under intermittent errors.
            metrics = {
                "chunks": size,
                "query_executions": len(jobs),
                "distinct_queries": len(queries),
                "concurrency": concurrency,
                "p50_ms": round(statistics.median(timings), 2) if timings else None,
                "p95_ms": round(percentile(timings, .95), 2) if timings else None,
                "p99_ms": round(percentile(timings, .99), 2) if timings else None,
                "throughput_qps": round(len(jobs) / batch_seconds, 2),
                "error_rate": len(errors) / len(jobs),
                "error_types": sorted(set(errors)),
                "hit_at_10": sum(1 for _elapsed, hit, _scope, error in results if hit and not error) / len(jobs),
                "scope_violations": sum(scope for _elapsed, _hit, scope, _error in results),
            }
            verdict, reasons = profile_verdict(metrics, limits, baseline_hit_rate=args.baseline_hit_rate)
            metrics.update({"status": verdict, "reasons": reasons})
            profiles.append(metrics)
    resource_reasons = []
    try:
        cpu_peak = float(resource_observation["cpu_peak_percent"])
        memory_peak = float(resource_observation["memory_peak_mb"])
        storage_limit = int(resource_observation["storage_limit_bytes"])
        hourly_cost = float(resource_observation["infrastructure_hourly_cost"])
    except (TypeError, ValueError):
        raise SystemExit("resource observation metrics must be numeric")
    if cpu_peak > limits["cpu_peak_percent"]:
        resource_reasons.append("cpu_peak_above_profile_limit")
    if memory_peak > limits["memory_peak_mb"]:
        resource_reasons.append("memory_peak_above_profile_limit")
    if index_bytes > storage_limit:
        resource_reasons.append("lexical_index_exceeds_declared_storage_limit")
    if hourly_cost < 0:
        resource_reasons.append("invalid_infrastructure_cost")
    passing_throughputs = [item.get("throughput_qps", 0) for item in profiles if item.get("status") == "PASS"]
    cost_per_query = (
        hourly_cost / (min(passing_throughputs) * 3600)
        if passing_throughputs and min(passing_throughputs) > 0 else None
    )
    resource_status = "PASS" if not resource_reasons else "FAIL"
    status = "PASS" if profiles and all(item["status"] == "PASS" for item in profiles) and resource_status == "PASS" else "BLOCKED"
    report = {"schema_version": 1, "gate": "KB-SCALE-01", "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": status, "deployment_profile": args.profile,
              "profile_limits": limits,
              "resource_observation": {key: resource_observation[key] for key in sorted(required_resource_fields)},
              "resource_status": resource_status, "resource_reasons": resource_reasons,
              "estimated_infrastructure_cost_per_query": cost_per_query,
              "tenant_id_hash": __import__("hashlib").sha256(str(tenant_id).encode()).hexdigest(),
              "revision_id": str(revision_id), "manifest_hash": manifest_hash,
              "image_digest": args.image_digest,
              "index_bytes": index_bytes, "profiles": profiles}
    output = ROOT / args.output; output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(status)
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
