# Phase C Code Review — Unified Ingestion Orchestration

**Review date:** 2026-08-26
**Gate decision:** PASS
**Migration head:** `ingestion_job_c1_008`

## Reviewed scope

- Versioned ingestion request and adapter registry contracts.
- Capability routing for document, spreadsheet, image, web and long audio inputs.
- Tenant-bound `IngestionJob` and append-only `IngestionJobEvent` lifecycle.
- Legacy document, URL and long-interview worker compatibility wiring.
- Quality/readiness state, retry attempts, RLS and migration reversibility.

## Findings fixed before gate

1. **Concurrent transition/event race:** job transitions now lock the job row before
   validating state and allocating the next event sequence.
2. **Concurrent idempotent create:** job creation now uses a savepoint and resolves a
   unique-key race to the winning job rather than leaving the session unusable.
3. **Idempotency semantic collision:** reuse now verifies revision, adapter and exact
   capability set; the same key cannot alias a different ingestion request.
4. **Retry attempt visibility:** audio failures are persisted for every attempt and a
   retry returns the job to running, incrementing `attempt`.
5. **URL worker omission:** web-page ingestion now uses the same lifecycle and readiness
   outcome as uploaded documents.
6. **Adapter metadata validation:** registry entries must expose a callable acceptance
   predicate in addition to key, version, capability, kinds and execution boundary.

## Verification

- PostgreSQL migration upgrade, Phase C downgrade/re-upgrade: passed.
- `alembic check`: no schema drift.
- Phase C/asset/capture focused tests: passed.
- Existing PostgreSQL document, connector, capture and retention tests: passed.
- Platform dependency direction, compile, Ruff correctness and diff checks: passed.

## Deliberately retained compatibility

- Existing endpoints and Celery task names remain stable. They now report into the
  common lifecycle instead of creating a third processing pipeline.
- Parser and STT implementations remain provider adapters behind the current worker
  boundary; replacing their algorithms is not required for lifecycle convergence.
