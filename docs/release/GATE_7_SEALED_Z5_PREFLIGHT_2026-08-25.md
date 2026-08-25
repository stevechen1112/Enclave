# Gate 7 — sealed Z5 preflight — 2026-08-25

## Decision

Status: **WAITING FOR INDEPENDENT CUSTODIAN EVIDENCE**.

Gate 7 is not passed and Gate 8 is not released. The implementation-side
preflight is complete, but the repository contains only the empty Z5 skeleton.
Creating a self-authored `PASS` would violate ADR-018 and the accepted release
plan: the repair implementer cannot also be the sealed-holdout custodian.

## Exact candidate binding

- Deployment manifest: `dm-14bd422353a946c64dfc1173`
- Backend image:
  `sha256:d5af9e57ebbe94d2cea1ca163cd235408e5f7872f369ad00892da9b486f14d00`
- Frontend candidate image:
  `sha256:78129a51bca15fff697d60ce75545f84c32fe83af82ffec8fe9094fdf3927cab`
- Acceptance KB revision: `ab1ecdff-3b1a-4e36-9b63-5fbdb6f0ace4`
- KB manifest:
  `42e3522d185bc7c213cea3c9b3a290b2751640ecd5814869e6e2b9b0156cbfde`
- Prepared handoff directory:
  `artifacts/knowledge/external_acceptance_handoff_dm-14bd422353a946c64dfc1173/`

The source gate passed with a clean deployment input set and no secret finding.
The handoff verifier returned `INTEGRITY_PASS_NOT_ATTESTED`, which is the only
valid status before independent evidence is supplied.

## Completed implementation-side checks

- Fresh deployment manifest generated from exact backend and frontend image IDs.
- Release source gate: `PASS`.
- Handoff bundle integrity: `INTEGRITY_PASS_NOT_ATTESTED`.
- External acceptance preflight with current evidence: correctly failed closed
  with `missing:z5_seal`.
- Z5 builder, seal validation, evaluation-gate, external-runner and handoff
  tests: `11 passed`.
- Ruff on all involved scripts: pass.
- Worktree remained clean; generated evidence stays outside source control.

## Evidence required from the custodian

Two different holdouts are required. Each one must satisfy all of the following:

1. A corpus not used in Z3, Z4, regression fixtures or product repair work.
2. At least 200 cases across at least four declared domains, with at least 50
   cases in every domain.
3. At least 20% mixed-language, abbreviation or part-number cases.
4. Independently extracted and reviewed ground-truth spans; Enclave chat output
   cannot be used as the ground truth.
5. Corpus manifest, questions, scoring contract and attestation hashed before
   the first run.
6. A named custodian identity different from the repair implementer.
7. Different corpus and question hashes between the two holdouts.

After opening, a holdout permanently becomes regression data. It cannot be
edited and rerun as new blind evidence.

## Pass thresholds

Each sealed first-run must have:

- strict assertions at least 90%;
- every domain at least 85%;
- required-slot coverage at least 95%;
- zero critical error;
- valid independent attestation and exact runtime/image/KB binding.

`KB-EVAL-01` passes only when two distinct completed first-runs meet all
thresholds. Until then the release gate must remain FAIL.

## Code-review conclusion

No implementation defect was found in the Gate 7 sealing and verification
machinery. It rejects empty corpora, fewer than 200 cases, insufficient domain
or mixed-language coverage, same custodian and implementer, overwritten seals,
missing attestations, duplicate corpus/question hashes and image/revision
mismatches.

The remaining dependency is external evidence, not code. No source behaviour
was changed, because the plan explicitly requires sealing the new holdout before
further knowledge-mainline tuning.
