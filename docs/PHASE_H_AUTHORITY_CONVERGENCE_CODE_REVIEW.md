# Phase H — Authority Convergence Code Review

**Review result:** implementation gate passed; production FORCE RLS and canonical read cutover remain intentionally gated by external evidence.

## Scope reviewed

- Generic `AssetAccessPolicy`, deny-first Asset visibility PEP, connector ACL and registry-boundary candidate revalidation.
- Video list, detail, review, media token, keyframe and retrieval access checks.
- Persistent `KnowledgeUnit`, immutable revisions, release images and release memberships.
- Transactional dual-write from KB promotion, approved video procedures and approved know-how; know-how retirement removes active membership.
- Active-release read semantics, explicit KB revision scope, source tombstone, ACL, applicability and module entitlement checks.
- Tenant-scoped bounded backfill, shadow/enforce configuration and PostgreSQL RLS readiness report.

## Findings and fixes made during review

1. **Empty KB release rejected.** This broke legitimate empty revision promotion. Knowledge-base releases now allow an empty immutable manifest.
2. **Retired know-how remained answerable.** Retirement now tombstones the stable unit and atomically publishes a release without it.
3. **Canonical enforce read initially omitted applicability and entitlement.** Role/entity applicability, high-risk authority and tenant module binding now fail closed.
4. **Shadow read failed on pre-migration test schemas.** Shadow mode now preserves legacy serving only for SQL/schema failures and logs the condition; enforce mode still propagates the failure.
5. **Alembic connection ambiguity.** Validation proved Alembic reads `POSTGRES_*`, not `DATABASE_URL`; the runbook now states the exact contract.
6. **Concurrent active release transition.** The old active row is locked and retired/flushed before the new candidate is activated, satisfying the partial unique index.

## Verification evidence

- Focused authority, ACL, video, retrieval, KB promotion and know-how suites passed.
- Full backend regression: first run produced 1176 passed / 1 failed; review fixed the pre-migration shadow compatibility failure and its focused regression passed.
- PostgreSQL clean upgrade to `knowledge_authority_h1_012`, `alembic check`, downgrade to `video_governance_f3_011`, and re-upgrade passed.
- `scripts/knowledge_authority_gate.py` reported four of four authority tables with RLS enabled, one policy each, no duplicate active release, and FORCE disabled.
- New and Phase H-scoped files pass Ruff and Python compilation.

## Deliberately open production gates

- `RLS_ENFORCEMENT_ENABLED` remains false until 14 consecutive days of production shadow evidence exist.
- `KNOWLEDGE_UNIT_READ_MODE` remains `shadow` until tenant-scoped parity, quality and latency gates pass.
- These are rollout evidence conditions, not incomplete implementation and must not be bypassed by configuration defaults.
