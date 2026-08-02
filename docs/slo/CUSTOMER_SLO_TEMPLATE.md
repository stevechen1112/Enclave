# Customer SLO Template (Enclave)

Copy per customer deployment. Defaults are starting points — adjust after capacity test.

| Metric | Target | Measurement |
|--------|--------|-------------|
| Query availability | ≥ 99.5% / month | Gateway `/health` + successful search rate |
| Search p95 latency | ≤ 2.5s (Standard) / ≤ 5s (Lite) | Prometheus histogram `enclave_gateway_search_latency_ms` |
| Ingest lag (upload → searchable) | ≤ 15 min p95 | Outbox + index timestamp |
| Connector sync lag | ≤ 30 min p95 (delta) | Connector `lag_seconds` |
| Permission revoke deny latency | ≤ 1s | Deny-set hit after revoke API |
| Projection convergence | ≤ 10 min p95 | `projection_status.state=converged` |
| Wiki freshness (when enabled) | ≤ 60 min after source change | Wiki `stale` → recompile |
| Backup RPO | ≤ 24h | Last successful `ops_lifecycle backup` |
| Backup RTO | ≤ 4h | Restore drill runbook |
| ACL leakage | **0** | `eval_retrieval_gate.py` + pen-test |

## Hard safety goals

- No uncited factual answers when product policy requires citations
- Revoke is deny-first at Gateway (do not wait for sidecar rebuild)
- Citation lineage object-level completeness = 100% on sampled answers (`validate_citation_lineage_online.py`)

## Lifecycle

- Support window: N and N-1 minor releases
- Security advisory SLA: Critical ≤ 7 days patch target after upstream fix available
- Telemetry: opt-in, default off
