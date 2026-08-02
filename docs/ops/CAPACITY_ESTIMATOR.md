# Capacity Estimator (docs-as-code)

| Profile | CPU | RAM | Disk | GPU | Concurrent users (approx) | Corpus size (approx) |
|---------|-----|-----|------|-----|---------------------------|----------------------|
| Lite | 4c | 8 GB | 50 GB | — | 10–25 | ≤ 50k chunks |
| Standard | 8c | 32 GB | 200 GB | 8 GB VRAM | 50–150 | ≤ 1M chunks |
| Enterprise | 16c+ | 64 GB+ | 500 GB+ | 24 GB+ / HA | 200+ | multi-million |

## Estimator inputs

```json
{
  "documents": 10000,
  "avg_pages": 8,
  "chunks_per_page": 3,
  "daily_queries": 5000,
  "connectors": ["nas_smb"],
  "wiki_enabled": true
}
```

Rough formula:

```
chunks ≈ documents * avg_pages * chunks_per_page
index_ram_gb ≈ chunks * 1024 * 4 / 1e9   # 1024-d float32 vectors
query_rps ≈ daily_queries / 28800        # 8h business day
```

Run `python scripts/preflight_check.py --profile <lite|standard|enterprise>` before install.
