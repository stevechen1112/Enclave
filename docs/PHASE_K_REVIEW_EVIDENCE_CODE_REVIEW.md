# Phase K Code Review — Review Inbox and Evidence Workspace

**Review date:** 2026-08-27
**Gate decision:** PASS
**Reviewed baseline:** Phase H authority + Phase I pack surfaces + Phase J intake

## Reviewed scope

- Source-neutral `/knowledge/review-items` inbox, detail, decision and constrained
  batch-decision contracts.
- Core canonical artifacts, compatibility file-classification items and optional
  MKA know-how decisions through a tenant-gated pack review provider.
- Typed document, image, table, audio, video and external-record evidence
  locators with local deep links.
- Three-column Evidence Workspace, responsive mobile steps, native keyboard
  controls, filters and explicit publication preview.
- KnowledgeUnit publication, reviewer separation-of-duty, ACL/policy gates,
  SOP precedence and audit evidence.

## Findings fixed before gate

1. **Unsafe cross-kind batch:** the first draft trusted the UI selection. The API
   now requires the same provider, source type and review policy, rejects every
   non-eligible item, excludes the legacy queue from batch publication and commits
   supported batch decisions in one transaction.
2. **Invalid KnowledgeUnit enum projection:** artifact kinds were initially passed
   directly as KnowledgeUnit types and medium risk was not a valid authority risk.
   A deliberate type/risk mapping now preserves the authority schema constraints.
3. **Evidence-free approval:** decision-time evaluation originally lacked the
   evidence spans loaded by the inbox. It now re-loads evidence under the locked
   artifact and blocks approval when no typed source locator exists.
4. **Hidden video SOP conflict:** a procedure candidate and its conflict report are
   separate artifacts. The workspace now nests the linked conflict report into the
   procedure decision, adds formal-SOP deep links and avoids a duplicate standalone
   queue decision.
5. **Non-idempotent retry:** a lost HTTP response could make a repeated generic
   decision return a conflict, and a multi-step MKA retry could advance twice with
   a new key. Core decisions now return the existing same decision; the UI retains
   one decision idempotency key across retries; duplicate audit rows are suppressed.
6. **Incomplete audit evidence:** audit rows initially recorded only provider and
   decision. They now include source/risk type, policy key/version, evidence IDs,
   acknowledgements and resolved conflict IDs.
7. **Optional-pack blast radius:** review provider loading/listing failures could
   take down the Base inbox. Optional providers are loaded only after deployment
   and tenant entitlement checks and fail closed in isolation.
8. **Legacy JSON portability:** PostgreSQL-only JSONB declarations prevented the
   generic compatibility contract from being exercised on SQLite. The model now
   uses generic JSON with a PostgreSQL JSONB variant without changing production
   storage semantics.
9. **Invalid interactive nesting:** the initial queue row placed a checkbox inside
   a button. Selection and row navigation are now sibling controls with independent
   keyboard focus and accessible labels.
10. **Rejected-only readiness:** completion originally advertised `searchable=true`
    even if every candidate was rejected. Final readiness now derives from an
    actual approved decision and records `review_rejected` otherwise.

## Gate evidence

- Full backend regression: **1,190 passed**, 7 dependency deprecation warnings.
- Focused review/pack/video suite: **37 passed**.
- PostgreSQL API test seals low-confidence fail-closed behavior, evidence locator,
  KnowledgeUnit publication, decision replay idempotency and one immutable audit
  record.
- Full frontend suite: **20 files / 74 tests passed**.
- Frontend ESLint and production TypeScript/Vite build: passed.
- Python compileall, Ruff for touched Python surfaces, OpenAPI route inventory and
  `git diff --check`: passed.

## Deliberate compatibility boundaries

- `/agent/review` and the specialized video review endpoint remain compatibility
  surfaces. New UI traffic uses the unified review contract.
- Legacy watch-folder classifications remain individually reviewable but are not
  batch-publishable until they have canonical asset/evidence authority.
- A pack contributes only a provider path; Base does not statically import MKA.
- Browser/device accessibility and real media seeking still require release-level
  acceptance on supported tablet and mobile hardware.

## Decision

No unresolved correctness, authorization, transaction, accessibility or
pack-isolation finding blocks Phase L. Phase K is accepted.
