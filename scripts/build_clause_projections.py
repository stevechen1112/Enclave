"""F4 — 為符合啟發式的已完成文件建立條款對照投影。

Usage:
  set POSTGRES_SERVER=localhost & set POSTGRES_PORT=5435
  python scripts/build_clause_projections.py
  python scripts/build_clause_projections.py --filename-substr ETI
  python scripts/build_clause_projections.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _llm():
    from app.config import settings
    import openai

    provider = str(getattr(settings, "LLM_PROVIDER", "openai")).lower()
    if provider == "gemini":
        key = getattr(settings, "GEMINI_API_KEY", "")
        model = getattr(settings, "GEMINI_MODEL", "gemini-3-flash-preview")
        client = openai.AsyncOpenAI(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        return client, model
    if provider == "ollama":
        url = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        model = getattr(settings, "OLLAMA_MODEL", "qwen3.6:35b")
        client = openai.AsyncOpenAI(api_key="ollama", base_url=f"{url.rstrip('/')}/v1/")
        return client, model
    key = getattr(settings, "OPENAI_API_KEY", "")
    model = getattr(settings, "OPENAI_MODEL", "gpt-4o")
    return openai.AsyncOpenAI(api_key=key), model


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy import create_engine, text as sql_text
    from app.db.session import SessionLocal
    from app.services.clause_projection import (
        extract_clauses_with_llm,
        needs_clause_projection,
        upsert_clause_projection,
    )

    url = os.getenv("DATABASE_URL", "")
    if not url:
        url = (
            f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}"
            f":{os.getenv('POSTGRES_PASSWORD', 'postgres')}"
            f"@{os.getenv('POSTGRES_SERVER', 'localhost')}"
            f":{os.getenv('POSTGRES_PORT', '5435')}"
            f"/{os.getenv('POSTGRES_DB', 'enclave')}"
        )
    engine = create_engine(url.replace("postgresql+asyncpg://", "postgresql://"))
    with engine.connect() as conn:
        rows = conn.execute(
            sql_text(
                """
                SELECT d.id::text, d.filename, d.version,
                       string_agg(c.text, E'\\n' ORDER BY c.chunk_index) AS body
                FROM documents d
                JOIN documentchunks c ON c.document_id = d.id
                WHERE d.status = 'completed' AND d.tombstoned_at IS NULL
                GROUP BY d.id, d.filename, d.version
                ORDER BY d.filename
                """
            )
        ).fetchall()

    client, model = _llm()
    built = 0
    skipped = 0
    for doc_id, filename, version, body in rows:
        if args.filename_substr and args.filename_substr.lower() not in (filename or "").lower():
            continue
        if not needs_clause_projection(filename or "", body or ""):
            skipped += 1
            continue
        print(f"projecting: {filename} ({len(body or '')} chars)")
        if args.dry_run:
            built += 1
            continue
        clauses = await extract_clauses_with_llm(body or "", llm_client=client, model=model)
        print(f"  clauses={len(clauses)}")
        db = SessionLocal()
        try:
            upsert_clause_projection(
                db=db,
                document_id=__import__("uuid").UUID(doc_id),
                revision=int(version or 1),
                clauses=clauses,
                source_chars=len(body or ""),
            )
            db.commit()
            built += 1
        finally:
            db.close()

    out = {
        "gate": "FD-CLAUSE",
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "PASS" if built > 0 or args.dry_run else "FAIL",
        "built": built,
        "skipped": skipped,
        "dry_run": bool(args.dry_run),
        "model": model,
    }
    art = ROOT / "artifacts" / "foundation_clause_projection_last_run.json"
    art.write_text(__import__("json").dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written:", art, out)
    return 0 if out["status"] == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--filename-substr", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
