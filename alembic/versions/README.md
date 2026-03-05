# ⚠️ DEPRECATED — Secondary Migration Directory

This directory contains **legacy/deprecated** migrations that are **NOT used** by Alembic.

The project's `alembic.ini` points to `app/db/migrations/` as the primary migration directory.
All of these migrations have been superseded by the primary chain.

## Why these exist

These files were created during early Phase 4/7/10 development before the primary migration
chain was consolidated. They are kept for reference only.

## Mapping to Primary Chain

| Secondary File | Status | Primary Equivalent |
|---|---|---|
| `t4_3_branding.py` | DEPRECATED | Branding columns not in current model |
| `t4_6_custom_domain.py` | DEPRECATED | → `c7c9c43b1a3d_add_custom_domains.py` |
| `t4_15_db_indexes.py` | DEPRECATED | Indexes already in initial schema |
| `t4_19_multi_region.py` | DEPRECATED | Region columns not in current model |
| `t7_5_feedback.py` | DEPRECATED | → `d1e2f3a4b5c6_phase10_13_tables.py` |
| `p10_watch_folders_and_review_items.py` | DEPRECATED | → `d1e2f3a4b5c6_phase10_13_tables.py` |

## DO NOT run these migrations

```bash
# Correct — uses primary chain:
alembic upgrade head

# These files will NOT be picked up since script_location = app/db/migrations
```
