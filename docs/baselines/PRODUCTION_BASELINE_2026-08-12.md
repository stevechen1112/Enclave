# Production Baseline — 2026-08-12

This document records the recoverable source baseline for the Enclave production
deployment at `https://kachu.tw`.

## Source of truth

- Git tag: `production-2026-08-12`
- Branch at capture time: `codex/production-baseline-20260812`
- Deployment directory: `/opt/enclave`
- Deployment method before this baseline: source snapshot/tarball (no `.git` on host)
- Source comparison: 452 of 453 deployment files were byte-identical to the
  workstation; the remaining file was `frontend/src/components/Layout.tsx`, where
  the production logout-menu hotfix is functionally identical and the workstation
  additionally contains an explanatory source comment.

## Runtime state

- Health: `{"status":"ok","env":"production"}`
- Alembic revision: `mka_p6_task_events_001 (head)`
- Web image: `sha256:a0ddb2074e59bb32d5df61610958079c8944ba46e58437785463fe696a5e6638`
- Worker image: `sha256:ac0043c88743b495c22cfe88e30a4ae503882c82f7a722f414fd9a1aafff1dfd`
- Beat image: `sha256:439d4fb36fd64f95cd5a9ab3b8e8ddb1abac75aaddf3d2aba1cf0514a6a49bb0`
- Frontend image: `sha256:ded3085c958c8cccf5462b87c5824ff14e9245a34834d7d8d6ce9b9d958df820`

The three backend process images are recorded separately because production had
historically rebuilt/recreated them at different times. A future release must
build one immutable backend image and deploy the same digest to web, worker, and
worker-beat.

## Verification performed for this baseline

- Backend: `922 passed, 10 skipped`
- MKA gates: `28/28 passed`
- Frontend: `38 passed`
- Frontend production build: passed
- Staged diff whitespace check: passed
- Hard-secret pattern scan: no real credentials detected; the only match was an
  explicit placeholder in `.env.production.example`.

Generated artifacts, one-off debug scripts, generated E2E reports, regenerated
test fixtures, and duplicate zero-byte root deployment scripts are intentionally
not part of this baseline.
