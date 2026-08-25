# Synthetic Demo Tenant Runbook

The six passwordless doors must point only to Enclave's canonical synthetic tenant.
They must never be attached to a customer, pilot, production, imported, or manually
assembled tenant.

## Identity

- Tenant UUID: `4a8a6ec2-9be7-5d43-a786-2bf4af10f3d1`
- Tenant name: `Enclave 合成展示工廠（非真實公司）`
- Exactly six allowlisted internal users under `@demo.enclave.invalid`
- The internal addresses are implementation identifiers, not login names exposed to visitors
- No Demo user is a platform superuser
- Password hashes are random and are not an alternate public login mechanism

## Corpus contract

The seed creates five first-party fictional manufacturing documents. Every one:

- starts with a synthetic-data notice;
- uses `source_type=synthetic_demo`;
- uses a virtual `demo://synthetic/...` path;
- has no connector/source-system binding;
- belongs to one active synthetic KB revision;
- has a matching immutable document version, profile, and chunk.

The tenant also receives canonical job-role assignments, module bindings, fixed-form
definitions, a fictional `EQ-100` QR scene, and one fictional know-how card.

## Commands

Run migrations and canonical application seeds first. Then:

```bash
python scripts/demo_tenant.py seed
python scripts/demo_tenant.py verify
```

Reset is destructive only inside the explicitly marked synthetic tenant and requires
the exact UUID as confirmation:

```bash
python scripts/demo_tenant.py reset \
  --confirm-reset 4a8a6ec2-9be7-5d43-a786-2bf4af10f3d1
```

Seed/reset run in one database transaction. A failed operation rolls back instead of
leaving a half-built tenant.

If an older deployment still has the retired shared-account personas, preserve
their historical rows but disable login before enabling the six doors:

```bash
python scripts/retire_legacy_demo_logins.py audit
python scripts/retire_legacy_demo_logins.py disable \
  --confirm-disable retire-legacy-demo-logins
```

Disablement refuses platform superusers, rotates the old password hashes and marks
the five retired persona users inactive. It does not delete their documents or
historical ownership records.

## Public Demo mutation boundary

- Sales, field, master, and newcomer doors may use tenant-internal chat, voice,
  task, form, know-how, interview, scene, and approval workflows.
- The viewer door may use read endpoints and conversational interactions only.
- The company-management door may approve synthetic Demo requests; system and
  organization settings remain read-only.
- All doors are blocked from document upload, source connectors, SSO, users,
  organization/system settings, payments, feature flags, and other unlisted writes.

The mutation allowlist is fail-closed. Add a new Demo-write route only with an
explicit threat review and reset-coverage test.

## Enablement order

1. Seed.
2. Verify and require `ok=true`.
3. Set `DEMO_TENANT_ID` to the canonical UUID.
4. Set `FIXED_FORM_ENABLED=true`, `KNOWHOW_CARD_ENABLED=true`, and keep
   `MODULE_ROUTER_ENABLED=true`. Startup now fails closed if a passwordless Demo
   is enabled without this complete capability set, instead of displaying doors
   whose forms cannot load.
5. Enable `DEMO_LOGIN_ENABLED=true` only on the public Demo deployment.
6. Exercise all six doors.

Ordinary production/customer deployments keep `DEMO_LOGIN_ENABLED=false`.

For a supervised public demonstration, reset immediately before opening the doors
and again after the session. The UI warns visitors not to enter real customer data,
personal data, or company secrets. Unattended multi-visitor public access requires
a separate per-session isolation design and is not authorized by this runbook.
