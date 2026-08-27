# Legacy surface retirement runbook

## Safety rule

Compatibility routes and schemas are not removed merely because a replacement exists. A surface must be registered in `app/platform/deprecations.py`, progress through `observe → warn → disable`, and have at least 30 complete days with no tenant traffic before a removal change is accepted.

The `observe` stage is intentionally never removal-eligible. Changing a stage is a reviewed release decision, not an automatic database action.

## Observe

Authenticated frontend compatibility redirects post `legacy_surface_used` audit events. Tenant administrators can read `GET /api/v1/deprecations`; operations can run:

```powershell
python scripts/audit_legacy_surfaces.py --tenant-id <tenant-uuid>
```

Do not infer zero traffic from missing global logs: run the report for every active tenant and confirm telemetry ingestion health first.

Registered legacy APIs also emit precise `Deprecation`, successor `Link` and
stage headers. Authenticated use is written to the same tenant-scoped audit
stream. Stable v1 endpoints are not marked deprecated.

Generate the cross-tenant removal artifact only from an operations context:

```powershell
$env:LEGACY_REMOVAL_REPORT_KEY='<32+ character secret from the operations vault>'
python scripts/generate_legacy_removal_report.py --output artifacts/ops/legacy-removal.json --require-eligible
```

Exit code `3` and report status `HOLD` are expected while any surface is still
observing, any tenant has traffic inside the window, or no active tenant was
enumerated. A signed HOLD report is evidence of a blocked gate, not permission to
remove code.

Before changing a registry stage, validate the next sequential transition:

```powershell
python scripts/authorize_legacy_transition.py --report artifacts/ops/legacy-removal.json --surface frontend.documents --current observe --target warn --tenant-notice-acknowledged
```

`warn → disable` additionally requires 30-day zero-traffic evidence for the
named surface across every active tenant. `disable → remove` also requires
`--rollback-evidence` that passes
`scripts/verify_modular_rollback.py`. The command does not edit source code.

## Warn

After customer notice and SDK/client migration, change only the selected registry entries to `warn`. Keep redirects working and add release notes with the replacement path and earliest removal date. Restart the 30-day clock if telemetry was unavailable or a hit is recorded.

## Disable and rollback rehearsal

Disable a surface behind a release flag before deleting code. Verify support contacts, browser bookmarks, PWA builds and customer integrations. For schema retirement, additionally require:

1. verified backup and restore in a non-production environment;
2. a downgrade/forward migration rehearsal;
3. zero reads and writes from application telemetry;
4. a named owner and rollback deadline.

The rollback evidence must inventory the following non-reversible or externally
durable objects. Application rollback never deletes them:

| Object | Authority / locator | Rollback rule |
|---|---|---|
| Original document, image, audio or video bytes | `AssetRevision.storage_uri` + `content_hash` | Preserve; old code may ignore an unknown media type. |
| Derived media and evidence | `DerivedArtifact.storage_uri`, `EvidenceSpan` locator | Preserve until both forward and rollback readers are verified. |
| Published knowledge | `KnowledgeUnitRevision` + release membership | Retire membership or switch release; do not mutate history. |
| Legacy document file | `Document.storage_path` | Preserve while document compatibility reads exist. |
| Long recording chunks | capture session/chunk storage key and retention policy | Apply policy only after the rollback window; never treat app rollback as retention expiry. |
| External connector record | source system/record/version and ACL snapshot | Do not delete the upstream record; retain tombstone and lineage. |

Before `disable`, rehearse restore into an isolated database/object prefix, render
every new migration's downgrade SQL, deploy the N-1 API/worker/frontend set, and
run canonical asset, review, sealed retrieval and tenant-isolation smoke tests.
Record backup digest, restore RTO, source/target revisions, image digests, object
counts and the named operator. Unit-test fixtures are not operator evidence.

## Remove

Removal PR evidence must include the per-tenant reports, observation dates, release notice, restore rehearsal and route-collision test. Never make data deletion part of the same release as the first route removal.
