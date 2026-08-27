# Phase B Code Review — Unified Asset Identity

**Review date:** 2026-08-26
**Gate decision:** PASS
**Migration head:** `asset_identity_b1_007`

## Reviewed scope

- `SourceAsset`, `AssetRevision`, `DerivedArtifact`, `EvidenceSpan` ORM and DDL.
- Tenant RLS, composite foreign keys, immutable revision identity and downgrade path.
- Document upload, connector, watcher/legacy worker and web-page dual-write.
- Long-form audio capture manifest, transcript artifacts and temporal evidence.
- Retention purge, legacy compatibility and bounded backfill command.

## Findings fixed before gate

1. **Cross-asset revision references:** capture and `supersedes` references originally
   guaranteed tenant equality but not asset equality. Both now use composite foreign
   keys containing `tenant_id + asset_id + revision_id`.
2. **Partial transaction commit on worker failure:** projection exceptions could reach
   the legacy failed-state update without rollback. Workers now rollback and reload the
   legacy row before recording failure.
3. **Incomplete tagged locator constraints:** generic time and range checks did not
   guarantee locator-specific payload. DB checks now require page/section, table cells,
   image region, audio time, video time/frame or external record identity as appropriate.
4. **Retention lineage state:** deleted audio objects left the source revision appearing
   available. Purge now marks the immutable revision lifecycle as `purged` while keeping
   hashes and evidence lineage.
5. **Pre-Phase-B queued captures:** old queued recordings had no canonical revision.
   The transcription worker now creates the deterministic manifest revision before STT.
6. **Web ingestion omission:** the separate URL worker now dual-writes a web-page source
   revision and extracted-text artifact.

## Verification

- PostgreSQL migration chain from empty schema to head: passed.
- Phase B downgrade to `demo_tenant_boundary_k6_006` and re-upgrade: passed.
- `alembic check`: no schema drift.
- Phase B contract/architecture regression: 75 passed.
- PostgreSQL document, connector, capture and retention integration: 29 passed.
- Python compile, Ruff correctness and `git diff --check`: passed.

## Deliberately deferred

- Production tenant backfill is an operational rollout, not a migration-side bulk update.
  Use `scripts/backfill_asset_identity.py` per tenant after deployment and observe counts.
- Read paths remain on `Document` during dual-write. Switching reads before reconciliation
  and telemetry pass would make rollback unsafe.
- KnowledgeUnit persistence and common ingestion orchestration belong to Phase C.
