# Phase I — Pack Full-Surface Code Review

**Review result:** passed.

## Scope reviewed

- Pack contracts now cover API router, worker task, projector, knowledge provider, permission resolver, lifecycle hook and frontend bundle contributions.
- MKA owns its API composition in `app/packs/mka/api.py`; the base API no longer enumerates MKA endpoint modules.
- Celery imports only task modules contributed by deployed packs and adds the MKA retention schedule only when that task module is deployed.
- Every MKA API route has a pack-level tenant entitlement dependency; a disabled tenant receives `module_disabled` even if it guesses a compatible URL.
- Frontend MKA route keys, lazy pages, guards and redirects live in the MKA bundle; the shared registry only composes installed bundles from bootstrap manifests.
- Bootstrap is read-only. Seeding moved to the explicit MKA lifecycle hook and existing demo/setup commands.
- Capability catalog reports deployment, tenant entitlement and runtime health as separate fields.

## Review findings and fixes

1. Removing implicit module seed correctly broke tests that relied on read-time mutation. Test setup was changed to call explicit provisioning; runtime mutation was not restored.
2. Deployment-only route removal did not by itself prevent a disabled tenant from calling deployed MKA routes. A router-wide tenant eligibility dependency was added.
3. Frontend shared registry still enumerated every MKA route key. Those mappings were moved into `frontend/src/modules/mka/routes.tsx`.
4. Worker task descriptors existed but Celery still imported `mka_tasks` statically. Import and beat schedule are now deployment-composed.

## Verification

- Enabled API route inventory: 311 routes, zero duplicate method/path pairs.
- Base-only process with `PACK_MKA_ENABLED=false`: 185 routes and zero `/knowhow`, `/job-modules`, `/knowledge-captures` or `/mka/*` paths.
- Pack, bootstrap, capability, job/task, know-how and MKA acceptance suites passed (133 relevant tests after explicit-provisioning fixture correction).
- Frontend: 17 files / 69 tests passed; TypeScript production build and ESLint passed.
- Pack/platform scoped Ruff and Python compilation passed.

## Compatibility

Public MKA URL paths are unchanged when the pack is deployed and entitled. Base deployments no longer expose placeholder MKA endpoints. Tenant provisioning must be explicit; GET bootstrap cannot repair incomplete setup and will instead return an empty/fail-closed experience.
