"""Fix corrupted markdown fences in CLOUD_AND_COMMERCIALIZATION_PLAN.md §4.1."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "CLOUD_AND_COMMERCIALIZATION_PLAN.md"
text = path.read_text(encoding="utf-8")
start = text.find("### 4.1 ")
end = text.find("### 4.2 ")
assert start > 0 and end > start, (start, end)

fence_open = "`" * 3 + "text"
fence_close = "`" * 3
diagram = """CDN / WAF (Cloudflare 或同等)
            |
Edge Gateway (TLS, HSTS, CSP, rate-limit)
       /                \\
Enclave API (N)      Celery Workers (N)
JWT/SSO/PEP/RLS      queues: default, ingest, bulk
       \\                /
        +------+------+------+------+
        |      |      |      |      |
   Postgres  Redis  Object Vector Sidecar Packs
   + RLS     cache  Store  pgvector (RAGFlow /
   (+read           R2/S3/ (+opt.    PipesHub /
    replica)        MinIO   Pinecone/ WeKnora)
                    tenant/ Qdrant)  B: per-customer
                    prefix           C: binding map

Observability: Sentry + Langfuse + Prometheus/Grafana + audit
"""

new_section = (
    "### 4.1 邏輯架構（形態 B／C 共用控制面契約）\n\n"
    + fence_open
    + "\n"
    + diagram
    + fence_close
    + "\n\n"
)
text = text[:start] + new_section + text[end:]
path.write_text(text, encoding="utf-8")
print("ok; U+FFFD=", text.count("\ufffd"))
print(text[start : start + 80].replace("`", "\\`"))
