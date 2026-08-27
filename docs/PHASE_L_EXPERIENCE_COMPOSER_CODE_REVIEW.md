# Phase L Code Review — Experience Composer and Role-aware Shell

**Review date:** 2026-08-27
**Gate decision:** PASS
**Reviewed baseline:** Phase H authority + Phase I pack surfaces + Phase J intake + Phase K review workspace

## Reviewed scope

- Server-owned role capabilities, primary navigation and default-home decisions.
- Bootstrap loading/error behavior and fail-closed route guards.
- Base-only, MKA and a future second-pack composition path.
- Role-aware home dashboard for personal work, knowledge health, processing,
  review workload and enabled applications.
- Capability catalog with separate deployment, tenant entitlement, runtime
  health and effective user permission fields.
- Desktop shell, mobile menu and command palette consuming the same server
  navigation payload.
- Feature controller/query hook/presentational split for the new home surface.

## Findings fixed before gate

1. **Browser-side role authority:** the frontend retained a complete role-to-
   capability table as a bootstrap fallback. It has been removed. Until an
   authenticated bootstrap is ready, capabilities and navigation are empty and
   protected UI stays in a skeleton or explicit unavailable state.
2. **Base users forced into manufacturing:** `field_work` existed on every Base
   role and `/job` was the employee/viewer home. It is now granted only when the
   entitled MKA UI manifest is present; Base-only users land on `/overview`.
3. **Pack ordering coupled to `/job`:** the composer and shell contained MKA path
   special cases. Pack navigation is now inserted uniformly and uses a generic
   application icon; a second test pack composes without a core route change.
4. **Untrusted default home:** a bootstrap default could point at a route absent
   from authorized navigation. Pack defaults must match their contributed
   navigation path, the server selects only a reachable default and the browser
   validates reachability again before redirecting.
5. **Misleading module permission:** possession of any pack permission initially
   marked every MKA module allowed. The catalog now consumes the effective
   job-role/module result and reports permission per module while retaining the
   permission-resolver fallback for packs without that model.
6. **Runtime/UI capability coupling:** removing Base `field_work` exposed that the
   Task Engine imported an API presentation helper and treated the UI capability
   as a static security role. Role authority moved to a shared service; domain
   workspace capability is derived from effective module/job context and the
   existing module ACL remains the deny-first authority.
7. **Core module page called optional APIs:** the system module page fetched
   Wiki, Graph and MKA endpoints directly. It now renders only the unified
   bootstrap capability catalog and cannot make a Base-only deployment probe
   optional domain APIs.
8. **Command dialog keyboard behavior:** the first command palette did not trap
   Tab focus or restore focus. It now focuses search on open, cycles focus inside
   the modal, closes with Escape and restores the invoking control.

## Gate evidence

- Full backend regression: **1,202 passed**, 7 dependency deprecation warnings.
- Focused experience, pack, task-engine and persona suites: **103 passed** across
  the final focused runs (37 composer/pack plus 66 task/persona tests).
- Full frontend suite: **22 files / 75 tests passed**.
- Frontend ESLint and production TypeScript/Vite build: passed.
- Ruff on new/touched Phase L surfaces (with legacy typing-modernization rules
  excluded only for the pre-existing Task Engine file) and `git diff --check`:
  passed.
- Six server persona combinations cover owner, admin, HR, employee, viewer and
  superuser; Base-only, MKA and future second-pack navigation are explicit tests.
- Accessibility checks cover semantic headings/table caption, modal name,
  initial focus, focus containment, mobile navigation parity and native controls.

## Deliberate compatibility boundary

- The central bootstrap still assembles legacy MKA job-role/workspace data and
  the historical tenant-admin surface remains a compatibility route. Phase M
  must instrument these paths and may retire their central mapping only after the
  30-day per-tenant zero-traffic condition. This gate does not claim that
  condition has elapsed.
- Real-device contrast, screen-reader and touch acceptance remains a release
  environment check; automated component coverage does not replace it.

## Decision

No unresolved Phase L correctness, authorization, navigation, pack-composition
or basic accessibility finding blocks Phase M. Phase L is accepted.
