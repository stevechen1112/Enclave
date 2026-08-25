# Gate 3 — Sidecar Runtime Health and Capability Honesty Review

Date: 2026-08-25  
Decision: **PASS**  
Production containment: passwordless Demo login remains disabled; Gate 3 is not deployed yet.

## Scope

- RAGFlow, PipesHub, and WeKnora service addressing
- startup configuration validation and runtime health probing
- health/capability API truthfulness and information exposure
- operator UI pack status
- optional dependency degradation without disabling the canonical Enclave index

## Implemented controls

1. Enabled sidecars use one normalized URL resolver and Compose service-DNS defaults.
2. Production/staging startup rejects loopback URLs, malformed URLs, and URLs containing credentials.
3. Token providers use the same validated endpoint as their adapters; conflicting localhost defaults were removed.
4. Application startup probes the canonical database-backed adapter and every enabled sidecar concurrently.
5. Disabled packs are excluded from adapter totals and do not degrade the core product.
6. An enabled but unhealthy pack is reported as `unavailable`/`degraded`, never as usable.
7. Feature lists are exposed only after a successful health probe.
8. Detailed probe errors and internal base URLs are removed from the operator API response.
9. Detailed `/api/v1/gateway/health` is superuser-only; the minimal public `/health` remains available for infrastructure checks.
10. Experience bootstrap, Wiki/Graph status APIs, and the Modules UI consume verified runtime state instead of equating a license flag with availability.
11. The canonical Enclave adapter now verifies database reachability instead of returning unconditional `healthy`.

## Code review findings and corrections

- **Fixed:** duplicated localhost defaults in service token providers.
- **Fixed:** optional disabled services previously counted only implicitly; status now distinguishes disabled, enabled, degraded, and unavailable.
- **Fixed:** RAGFlow was projection-only and absent from gateway health; the health adapter set now includes it.
- **Fixed during review:** health construction initially instantiated unused duplicate PipesHub/WeKnora projection adapters; construction now adds only the projection-only RAGFlow adapter.
- **Fixed during review:** Wiki/Graph product notices could still show static Beta/API labels while their runtime was down; responses and product-status headers now overlay verified runtime state.
- **Fixed during review:** raw connection exceptions and internal URLs could have reached the detailed health payload; only a stable `probe_failed` reason is returned.
- **Accepted existing debt:** several older touched Python modules have pre-existing full-project Ruff modernization/import-order findings. New Gate 3 files pass the complete configured Ruff rules; all Gate 3 files pass critical syntax/undefined-name checks. No bulk unrelated rewrite was performed in this gate.

## Verification evidence

- Gate 3 and related backend suite: **93/93 passed** before final review additions; the dedicated final Gate 3 suite is **13/13 passed**.
- Frontend Vitest: **47/47 passed**.
- Frontend ESLint: **passed**.
- Frontend TypeScript and production Vite build: **passed**.
- New Gate 3 files, full Ruff rule set: **passed**.
- Python compile check for changed runtime modules: **passed**.
- `docker compose ... --profile standard config --quiet`: **passed** with pinned image and pack env files.
- `git diff --check`: **passed** (line-ending notices only).

## Residual operational truth

This gate makes unhealthy or unconfigured Sidecars visible and non-claimable; it does not certify the third-party services themselves. RAGFlow, PipesHub, and WeKnora must still be started with their required credentials/data stores and pass live integration flows in later staging and release gates before they count as commercially supported capabilities.

## Approval

No unresolved Gate 3 severity P0/P1/P2 code-review finding remains. Gate 4 may begin.
