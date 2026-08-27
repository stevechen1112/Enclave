# P3 Multimodal Golden Corpus

This directory defines the reusable, synthetic cross-modal ground truth contract.
It is safe to retain in the repository and contains no customer data. `generated://`
sources are deterministic fixture recipes exercised by ingestion tests and staging
live smoke; they are identifiers, not claims that a media binary is checked in.

The corpus deliberately separates three evidence classes:

- `mock_contract`: validates schema, terminal-state and governance policy only.
- `internal_replay`: consumes an immutable result bundle from actual parsers or
  providers. The CLI refuses to synthesize this mode.
- `degraded`: verifies disabled or failed providers abstain safely, create review
  work when necessary and do not invent evidence.

Only `internal_replay` may support extraction or model-accuracy claims. Contract
and degraded reports remain CI gates because they prevent safety regressions even
when paid or hardware-dependent providers are unavailable.

The v1 slices cover native/scanned PDF, DOCX, XLSX, CSV, printed/handwritten image,
quiet/noisy/multi-speaker/long audio, and captioned/silent/handheld/equipment video.
Every case binds tenant, revision and typed evidence locators. High-risk answers,
unresolved SOP conflicts, stale revisions, cross-tenant evidence, hallucinations
and low-confidence content without review are zero-tolerance failures.
