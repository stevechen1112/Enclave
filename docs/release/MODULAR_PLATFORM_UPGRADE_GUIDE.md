# Modular platform upgrade guide

## Configuration

- Core multi-tenant knowledge remains enabled independently of optional packs.
- `PACK_MKA_ENABLED` controls Manufacturing Knowledge Assistant contributions and UI modules.
- `VIDEO_INGESTION_ENABLED` controls governed video ingestion; size, duration, resolution, codec, keyframe and audio chunk limits are configured with the `VIDEO_*` settings documented in the environment templates.

## Database sequence

1. Back up the database and object store.
2. Run `python -m alembic upgrade head` before deploying workers or API instances that write canonical assets.
3. Deploy API and workers from the same release. Old document paths dual-write to canonical Asset identity during the compatibility window.
4. Run `python -m alembic check` and the migration smoke tests.
5. Do not downgrade F2/F3 artifact-kind constraints while rows of the newer kind exist; restore or explicitly archive those rows under an approved rollback plan.

## Client changes

- Use `/knowledge/*` frontend routes. Old top-level routes remain telemetry-instrumented redirects during their announced window.
- `GET /api/v1/job-modules` now has one canonical implementation and returns an array containing module definition plus tenant binding fields.
- Video media URLs returned by the review API contain short-lived, resource-bound tokens and should be used as returned; clients must not persist them.
- Video procedure publication can return HTTP 409 for unresolved SOP conflicts or missing high-risk acknowledgement. Clients must show the conflict evidence and obtain an authorized reviewer decision.
- Follow `docs/release/LEGACY_API_SDK_MIGRATION.md` for precise legacy response
  headers and successor contracts. `X-API-Version: v1` alone does not mean an
  endpoint is deprecated.

## Rollback

Application rollback is allowed only while the target version understands every persisted artifact kind. Use the tested Alembic downgrade only in an isolated rehearsal or after confirming no newer artifacts exist. Object-store assets are immutable and must not be deleted as part of an application rollback.
