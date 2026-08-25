# Gate 4 — Synthetic Demo Tenant and Code Review

Date: 2026-08-25  
Result: **PASS for supervised demonstration; production remains disabled**

## Release contract

- One fixed tenant UUID and an unmistakable non-real-company name.
- Exactly six allowlisted passwordless personas; none is a platform superuser.
- Internal persona identifiers use the reserved `.invalid` namespace and do not
  collide with or expose retired account names.
- Exactly five Enclave-authored fictional manufacturing documents, one active KB
  revision, five chunks and canonical `answer_ready=true` state.
- Exact canonical job roles, module bindings, forms, QR scene and synthetic
  know-how card.
- No connector instance, SSO secret, imported path or external source binding.
- Fail-closed mutation scopes: workflow, conversational interaction, approval,
  or no unlisted mutation.
- Transactional seed/reset/verification with an exact UUID reset confirmation.

## Code-review findings fixed before PASS

1. Retired scripts still used shared Demo credentials. All release-facing browser,
   walkthrough and smoke paths now use `/auth/login/demo` persona doors.
2. Three legacy remote scripts could SSH to an old host or directly alter schema.
   They were replaced by supported local initialization, read-only diagnostics and
   Alembic-only guidance.
3. A legacy helper could import sidecar content into the public Demo. It now fails
   closed and directs tests to a separately authenticated staging tenant.
4. The admin door could otherwise drift into platform-superuser access. Login now
   rejects every Demo superuser identity.
5. The viewer response and JWT disagreed about read-only status. The claim now
   matches the visible contract while permitting only conversational interaction.
6. Auto-binding previously matched any `is_demo` tenant. It now matches the fixed
   canonical Demo UUID as well.
7. Verification originally accepted extra roles/forms/scenes. It now compares
   exact canonical sets and a regression test proves unexpected content fails.
8. Old globally unique persona emails could block a safe seed. New door identities
   use non-colliding internal `.invalid` addresses. A separate retirement command
   disables old shared-account logins without deleting historical ownership rows.
9. Frontend regression found stale copy expecting unrestricted management settings.
   The assertion and UI now explicitly state that system settings cannot be changed.
10. Release-source review found that the admin mutation allowlist used an internal
    module name rather than the real `/approvals/{id}/{decision}` route. It now
    permits only approve/reject/request-changes and direct know-how approval, while
    continuing to block approval-policy changes and all other management writes.

## Verification evidence

- Demo/config/login/lifecycle tests: **21 passed**.
- Role permissions, job runtime, task engine, module platform, bootstrap, MKA,
  document readiness/visibility, knowledge control and voice contracts:
  **123 passed**.
- Frontend unit tests: **47 passed**.
- Frontend ESLint: **passed**.
- Production TypeScript/Vite build: **passed**.
- New/changed Gate 4 Python files: Ruff **passed**.
- Critical Python correctness rules on integrated endpoints: **passed**.
- `compileall`: **passed**.
- Real isolated database sequence `seed -> verify -> reset -> verify`: **passed**;
  reset removed 78 tenant-scoped rows and rebuilt the exact corpus.
- `git diff --check`: **passed**.

Third-party `pkg_resources`/namespace-package deprecation warnings remain; they do
not represent a Gate 4 correctness failure and will be handled in dependency
hardening.

## Operating boundary

This gate authorizes the six doors only for supervised demonstrations with a reset
immediately before and after the session. The page warns against entering real
customer data, personal data or company secrets. Unattended multi-visitor public
access still requires per-session isolation and will be addressed in the later
security/operations gate. Until that gate passes, production keeps
`DEMO_LOGIN_ENABLED=false`.
