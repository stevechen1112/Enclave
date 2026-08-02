"""Wiki live-compile eval gate (D3): prove Auto-Wiki actually compiled pages.

This replaces the health-only live check. It PASSes only if the configured
WeKnora wiki KB has *real* compiled pages: an index page plus summary pages
that carry non-trivial content and source_refs back to their source documents.

Writes artifacts/wiki_live_compile_last_run.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "wiki_live_compile_last_run.json"

# A page counts as "real compiled content" only above this many characters.
MIN_CONTENT_CHARS = 100


# Credential / routing keys must come from .env, not a stale shell var: a
# leftover 24h JWT in the environment is exactly the failure mode A3/A4 fixed,
# and an eval gate must test the *configured* credential.
_FORCE_OVERRIDE = ("WEKNORA_API_KEY", "WEKNORA_KB_ID", "WEKNORA_BASE_URL", "WEKNORA_ENABLED")


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k in _FORCE_OVERRIDE:
                os.environ[k] = v
            else:
                os.environ.setdefault(k, v)


def _headers() -> dict:
    key = os.getenv("WEKNORA_API_KEY", "")
    # A4: long-lived sk- tenant key authenticates via X-API-Key, not Bearer.
    if key.startswith("sk-"):
        return {"X-API-Key": key}
    return {"Authorization": f"Bearer {key}"} if key else {}


def _find_wiki_kb(client) -> dict:
    """Resolve the wiki KB id: explicit WEKNORA_KB_ID wins, else first wiki-enabled KB."""
    explicit = os.getenv("WEKNORA_KB_ID", "")
    if explicit:
        return {"kb_id": explicit, "source": "WEKNORA_KB_ID"}
    resp = client.get("/api/v1/knowledge-bases", params={"page": 1, "page_size": 100})
    resp.raise_for_status()
    for kb in resp.json().get("data") or []:
        if (kb.get("capabilities") or {}).get("wiki"):
            return {"kb_id": kb.get("id"), "source": "discovered", "name": kb.get("name")}
    return {"kb_id": None, "source": "none"}


def main() -> int:
    _load_env()
    import httpx

    enabled = os.getenv("WEKNORA_ENABLED", "").lower() == "true"
    base = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081").rstrip("/")
    checks: dict = {"enabled": enabled, "base_url": base}

    if not enabled:
        checks["passed"] = False
        checks["error"] = "WEKNORA_ENABLED not true"
    else:
        try:
            with httpx.Client(base_url=base, headers=_headers(), timeout=30.0) as client:
                kbinfo = _find_wiki_kb(client)
                checks["kb"] = kbinfo
                kb_id = kbinfo.get("kb_id")
                if not kb_id:
                    checks["passed"] = False
                    checks["error"] = "no wiki-enabled knowledge base found"
                else:
                    resp = client.get(
                        f"/api/v1/knowledgebase/{kb_id}/wiki/pages",
                        params={"page": 1, "page_size": 100},
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    pages = body.get("pages") or (body.get("data") or {}).get("pages") or []
                    total = body.get("total") or (body.get("data") or {}).get("total") or len(pages)

                    summaries = [p for p in pages if p.get("page_type") == "summary"]
                    index_pages = [p for p in pages if p.get("page_type") == "index"]
                    real_summaries = [
                        p for p in summaries
                        if len(p.get("content") or "") >= MIN_CONTENT_CHARS and p.get("source_refs")
                    ]

                    checks["total_pages"] = total
                    checks["index_pages"] = len(index_pages)
                    checks["summary_pages"] = len(summaries)
                    checks["real_summary_pages"] = len(real_summaries)
                    checks["pages"] = [
                        {
                            "slug": p.get("slug"),
                            "page_type": p.get("page_type"),
                            "status": p.get("status"),
                            "content_len": len(p.get("content") or ""),
                            "source_refs": p.get("source_refs"),
                        }
                        for p in pages
                    ]
                    checks["passed"] = bool(
                        total > 0
                        and len(index_pages) >= 1
                        and len(real_summaries) >= 1
                    )
        except Exception as exc:  # noqa: BLE001 - eval gate records the failure
            checks["passed"] = False
            checks["error"] = str(exc)[:500]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if checks.get("passed") else "FAIL",
        "checks": checks,
        "note": "D3: PASS requires a live wiki KB with an index page and >=1 summary page "
                f"carrying >={MIN_CONTENT_CHARS} chars and source_refs (not a health check).",
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
