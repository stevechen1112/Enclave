# Media Quality V2 corpus contract

This directory contains a **template only**. It is useful for evaluator and
pipeline contract tests, but is not a sealed holdout and is not real customer
accuracy evidence.

Allowed classifications are `development_regression`, `sealed_holdout`,
`tenant_acceptance`, and `production_shadow`. Tenant acceptance manifests must
name a truth owner. Sealed manifests must record `sealed_at`; results must be
bound to the immutable manifest hash and an exact runtime manifest hash.

The production certification corpus target remains at least 60 audio and 60
video items with a 20% sealed holdout. Those source files and independent human
labels must be supplied and signed off separately.
