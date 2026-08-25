# Production six-door Demo hotfix and acceptance — 2026-08-25

## Decision

The six passwordless Demo doors are enabled on `https://kachu.tw/login` and
accepted in the real production browser. The public Demo is bound to the
canonical synthetic tenant only. No production customer document is visible
from the Demo tenant.

This hotfix is complete for six-door access, logout, isolated synthetic data,
and role-specific saved conversations. It does not claim that every Enclave
workflow or the broader knowledge-quality programme is complete.

## Production change set

- Release baseline: `af3facf0f9ac8f62c8050fb1bbf25383f67f3e77`
  (`rc-2026.08.25-gate6`).
- Demo administrator interaction fix: `92a3ae1`.
- Runtime backend image:
  `sha256:d5af9e57ebbe94d2cea1ca163cd235408e5f7872f369ad00892da9b486f14d00`.
- Backend runtime user: `enclave`.
- Database revision: `demo_tenant_boundary_k6_006 (head)`.
- Frontend was intentionally not changed by this backend hotfix.

The administrator fix permits the existing `approval` Demo scope to use only
the already constrained interaction prefixes (chat, voice, interaction and
voice realtime). Uploads, policy mutation, system settings and external
connectors remain fail-closed.

## Root causes

1. Production had the six-door frontend but Demo login was disabled and the
   backend did not expose the required candidate implementation, so a door
   returned `Not found`.
2. After the isolated Demo tenant was enabled, the company-management persona
   could view the overview but could not ask questions. Its `approval` scope
   allowed decisions but omitted the interaction allowlist, causing the chat
   stream request to return HTTP 403.
3. During the second deployment check, combining the development and production
   Compose files introduced the development source bind mount and masked the
   immutable image. The release was rejected immediately, rolled back, and
   redeployed using the repository-prescribed production command with
   `docker-compose.prod.yml` only. Final inspection proves that `/code` is not a
   host bind mount; only the uploads volume is mounted.

## Rollback evidence

- Environment backup:
  `/opt/enclave/backups/env_pre_demo_hotfix_20260825_1015`
- PostgreSQL custom-format backup:
  `/opt/enclave/backups/enclave_pre_demo_hotfix_20260825_1015.dump`
- Backup SHA-256:
  `b243bcb2297a67f293bae3f785c86260b2d10c907cafd1d661ea864aba6537ca`
- Original pre-Demo backend image:
  `sha256:5f0b0ad1e6aa5707146080c4288472589444ea92c3b12a77cd5786fc30632fb0`
- Pre-administrator-chat backend rollback image:
  `sha256:d80bbe0b6a25b155707988def619744f0b87750c9e4c38d3d045d0dc62ef1e50`

The database backup passed `pg_restore --list` before mutation.

## Canonical Demo boundary

- Tenant UUID: `4a8a6ec2-9be7-5d43-a786-2bf4af10f3d1`
- Six exact internal identities under `demo.enclave.invalid`
- Five exact synthetic documents and chunks
- All five documents are `answer_ready`
- One exact knowledge base
- Exact job roles, assignments, module bindings, forms, scene and know-how card
- No platform superuser
- No connectors
- Empty sidecar binding
- No SSO secrets

The independent production verifier returned `ok: true` for every invariant.

## Browser acceptance

All checks were performed against `https://kachu.tw`, not localhost.

| Door | Landing | Visible role workspace | Logout |
|---|---|---|---|
| Sales | `/job` | quote, specification/SOP and knowledge actions | pass |
| Equipment field | `/job` | incident, handover, daily report, maintenance and knowledge actions | pass |
| Master | `/job` | master know-how, interview capture, maintenance and knowledge actions | pass |
| Newcomer | `/job` | master know-how, newcomer training and knowledge actions | pass |
| Supervisor viewer | `/job` | read-only knowledge interaction | pass |
| Company management | `/overview` | overview, governance/system navigation and knowledge interaction | pass |

The viewer document list contained exactly five `DEMO_` documents and no upload
control. The management overview reported exactly five employee-searchable
documents. Browser console warnings and errors were empty after the final pass.

## Saved production Demo conversations

The real UI created and persisted role-specific synthetic conversations. The
database audit found one two-message conversation for each non-admin persona and
two two-message conversations for the management persona.

| Persona | Demonstration topic | Result |
|---|---|---|
| Sales | P-100 price, MOQ, lead time, discount and terms | correct, cited P-100 Demo rule |
| Equipment field | EQ-100 five-step changeover and E-07 safety response | correct, cited EQ-100 Demo SOP |
| Master | tension-drift diagnosis and prohibited workaround | correct, cited master Demo know-how |
| Newcomer | required PPE and abnormal-equipment safety sequence | correct, cited Demo safety handbook |
| Supervisor viewer | synthetic 8D containment, cause, correction, verification and approval | correct, cited Demo 8D example |
| Company management | five-document catalogue and a P-100 spot check | correct, cited synthetic sources |

Failed exploratory questions were deleted rather than left in the public Demo.

## Test and code-review evidence

- Full backend regression: `1095 passed`.
- Demo/security/tenant/sidecar targeted regression: `35 passed`.
- Six-door frontend targeted regression: `10 passed`.
- Ruff on the changed Python files: pass.
- `git diff --check`: pass.
- Runtime image smoke test:
  - management scope can reach `/api/v1/chat/chat/stream`;
  - management scope cannot reach `/api/v1/admin/users`.
- Production container health: web and worker healthy; worker-beat running.
- Post-readiness backend critical log scan: empty.
- Post-readiness gateway HTTP 5xx scan: empty.
- External `/`, `/login` and `/health`: HTTP 200.

### Code-review conclusion

No blocking finding remains in the six-door access hotfix. The permission delta
is deliberately narrower than the employee workflow scope, is covered by both
unit and middleware integration assertions, and retains the existing
fail-closed policy mutations.

Two knowledge-experience findings remain outside this access hotfix and must be
handled in the knowledge-quality gates: an underspecified follow-up can lose the
previous turn's entity context and refuse despite a relevant source, and the
evidence drawer can include low-relevance catalogue entries or display a score
above 100%. Neither affected the correctness of the retained demonstration
answers, but both should be corrected before final GA claims.

## Production operation rule learned

Production backend services must be recreated with `docker-compose.prod.yml`
only (plus explicitly approved production sidecar overlays). Never merge the
development `docker-compose.yml`, because it bind-mounts the host source tree
over `/code` and defeats immutable-image verification.
