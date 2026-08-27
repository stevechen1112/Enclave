# Phase J Code Review — Unified Knowledge Intake and Asset Library

**Review date:** 2026-08-27
**Gate decision:** PASS
**Reviewed baseline:** Phase H authority + Phase I pack surfaces

## Reviewed scope

- Media-neutral `/knowledge/assets` create, list, detail, revision, status,
  event, retry and tombstone contract.
- File, URL, direct API record and capture-manifest intake routing.
- Canonical tenant/department ACL, classification, source namespace,
  idempotency, hash dedupe, file scan, quota and lifecycle enforcement.
- Base long-form audio worker and existing document/video worker bridges.
- Asset Library, global Add Knowledge action, mobile camera/audio/video capture,
  generic detail shell, processing timeline and revision history.
- Compatibility preservation for existing document, video and long-interview APIs.

## Findings fixed before gate

1. **Canonical parent/child insert ordering:** a new `SourceAsset` initially relied
   on an ORM relationship that does not exist to order `AssetRevision` inserts.
   The asset is now explicitly flushed first; the regression test reproduced and
   seals the real foreign-key failure.
2. **False retry state:** retry originally changed a job to `running` without
   dispatching work. It now dispatches by adapter for document, URL, audio and
   video; dispatch failures become explicit retryable failures rather than stuck
   processing states.
3. **Missing Base audio execution:** raw audio uploads previously created a job
   but had no worker. The Base worker now transcribes, preserves speaker/time
   evidence, creates review-required transcript artifacts and records governed
   job transitions.
4. **URL SSRF boundary:** URL ingestion initially checked only the scheme. The
   worker now rejects credentialed, loopback, private, link-local and reserved
   targets, revalidates every redirect, disables environment proxies, caps
   redirects and enforces a 10 MiB response ceiling.
5. **URL source immutability:** the URL string was initially at risk of being
   treated as the first content revision. URL intake now creates only the stable
   asset identity; the first immutable revision is produced after the worker
   fetches and hashes the actual content.
6. **Direct API/connector collision:** manually submitted external IDs originally
   occupied the connector namespace and could later collide with connector ACL
   materialization. Direct records now use an `api:<source>` namespace and retain
   the requested upstream name as metadata.
7. **Temporary/object orphan cleanup:** rejected or failed audio intake now removes
   temporary bytes and deletes the stored object when DB/job creation fails.
8. **Cross-media quota gap:** tenant storage usage previously counted only legacy
   `Document.file_size`. It now adds canonical current revisions not represented
   by a live Document, without double counting projected documents.
9. **Cross-tenant governance input:** department IDs and data-classification values
   are validated before persistence; malformed ACL state continues to fail closed.
10. **Asset Library N+1 query:** list serialization originally loaded revision and
    job state per row. Revisions and current jobs are now batch-loaded after ACL
    filtering.
11. **Dead global action:** the Add Knowledge button initially followed the generic
    content-creation permission while the route required upload permission. Both
    now use the same capability, so the UI cannot advertise an inaccessible path.

## Gate evidence

- Full backend regression after the core Phase J implementation: **1,186 passed**.
- Post-review focused backend suites for unified assets, SSRF, authority and quota:
  passed.
- Phase J/asset/video/pack integration selection: **74 passed** before final quota
  hardening; affected quota suite after hardening: **13 passed**.
- Full frontend suite: **19 files / 72 tests passed**.
- Frontend ESLint and production TypeScript/Vite build: passed.
- Python compileall, Ruff for touched Python surfaces, Celery audio task registry,
  route inventory and `git diff --check`: passed.

## Compatibility and operational boundaries

- Existing `/documents`, `/media/videos` and `/knowledge-captures` routes remain
  available as compatibility adapters and retain their specialized viewers.
- Capture manifests describe an already durable capture source; browser file/audio/
  video capture uploads bytes through the unified endpoint. Resumable multi-chunk
  interviews continue to use the existing long-capture API while projecting into
  the same canonical asset authority.
- A successfully parsed artifact is still not answer-ready. Audio/video candidates
  remain `review_required`; only active KnowledgeUnit release membership grants
  retrieval authority.
- Production accessibility still requires device/browser acceptance in the release
  environment. The implemented controls provide semantic labels, keyboard-native
  inputs, progress semantics, responsive layouts and minimum touch targets.

## Decision

No unresolved correctness, authorization or data-integrity finding blocks Phase K.
Phase J is accepted; unified review/evidence work may begin.
