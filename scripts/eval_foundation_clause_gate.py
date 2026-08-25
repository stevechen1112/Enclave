"""FD-CLAUSE — 跨語條款對照投影閘門（FOUNDATION F4）。

1. DB：至少一份 active clause_projection artifact，clauses≥1
2. Wiki：對應 Enclave WikiPage（page_type=comparison, provider=enclave）存在
3. Chat：固定跨語對照查詢 → intent=translate、clause_projections≥1、
   答案含條款訊號（中／英標題或條號）

禁止題號白名單；查詢字串固定。

Usage:
  python scripts/eval_foundation_clause_gate.py [--base http://localhost:8001]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "foundation_clause_last_run.json"

QUERY = "ETI Base Code 條款編號與標題對照"
ANSWER_SIGNALS = (
    "Employment",
    "Forced",
    "Association",
    "Working",
    "就業",
    "強迫",
    "結社",
    "工時",
    "1.",
    "條款",
)


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url.replace("postgresql+asyncpg://", "postgresql://")
    return (
        f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}"
        f":{os.getenv('POSTGRES_PASSWORD', 'postgres')}"
        f"@{os.getenv('POSTGRES_SERVER', 'localhost')}"
        f":{os.getenv('POSTGRES_PORT', '5435')}"
        f"/{os.getenv('POSTGRES_DB', 'enclave')}"
    )


def check_db() -> dict:
    from sqlalchemy import create_engine, text

    engine = create_engine(_db_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        art = conn.execute(
            text(
                """
                SELECT d.filename, a.metadata_json
                FROM document_artifacts a
                JOIN documents d ON d.id = a.document_id
                WHERE a.artifact_type = 'clause_projection'
                  AND a.status = 'active'
                LIMIT 10
                """
            )
        ).fetchall()
        parsed = []
        for filename, meta in art:
            if isinstance(meta, str):
                meta = json.loads(meta)
            n = len((meta or {}).get("clauses") or [])
            parsed.append((filename, n))
        parsed.sort(key=lambda x: x[1], reverse=True)
        art = parsed[:5]
        wiki = conn.execute(
            text(
                """
                SELECT slug, title, provider, page_type, status
                FROM wiki_pages
                WHERE page_type = 'comparison'
                  AND provider = 'enclave'
                  AND tombstoned_at IS NULL
                  AND slug LIKE 'clause-projection-%'
                LIMIT 5
                """
            )
        ).fetchall()
    return {
        "artifacts": [{"filename": r[0], "clauses": int(r[1])} for r in art],
        "wiki_pages": [
            {
                "slug": r[0],
                "title": r[1],
                "provider": r[2],
                "page_type": r[3],
                "status": r[4],
            }
            for r in wiki
        ],
    }


def login(client: httpx.Client) -> None:
    r = client.post(
        "/api/v1/auth/login/access-token",
        data={
            "username": os.environ["EVAL_ADMIN_EMAIL"],
            "password": os.environ["EVAL_ADMIN_PASSWORD"],
        },
    )
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def stream_chat(client: httpx.Client, question: str, timeout: int = 180) -> dict:
    retrieval: dict = {}
    answer: list[str] = []
    with client.stream(
        "POST",
        "/api/v1/chat/chat/stream",
        json={"question": question},
        headers={"Accept": "text/event-stream"},
        timeout=timeout,
    ) as resp:
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"chat stream HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "retrieval":
                retrieval = d.get("retrieval") or {}
            elif d.get("type") == "token" and "content" in d:
                answer.append(d["content"])
    return {"retrieval": retrieval, "answer": "".join(answer)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    args = ap.parse_args()
    t0 = time.time()
    violations: list[str] = []
    cases: list[dict] = []
    status = "PASS"
    db_obs: dict = {}

    try:
        db_obs = check_db()
        arts = db_obs.get("artifacts") or []
        max_clauses = max((a["clauses"] for a in arts), default=0)
        if max_clauses < 1:
            violations.append(
                "clause_projection_missing: no active clause_projection with clauses≥1"
            )
        cases.append(
            {
                "id": "db_projection",
                "verdict": "fail" if max_clauses < 1 else "pass",
                "violations": [] if max_clauses >= 1 else list(violations[-1:]),
                "observed": {"artifacts": arts},
            }
        )

        wiki = db_obs.get("wiki_pages") or []
        if not wiki:
            violations.append(
                "wiki_sync_missing: no enclave comparison wiki page for clause-projection-*"
            )
        cases.append(
            {
                "id": "wiki_sync",
                "verdict": "fail" if not wiki else "pass",
                "violations": (
                    ["wiki_sync_missing"] if not wiki else []
                ),
                "observed": {"wiki_pages": wiki},
            }
        )

        with httpx.Client(base_url=args.base, timeout=180.0) as client:
            login(client)
            chat = stream_chat(client, QUERY)
        retrieval = chat["retrieval"]
        answer = chat["answer"]
        qp = retrieval.get("query_plan") or {}
        chat_violations = []
        if qp.get("intent") != "translate":
            chat_violations.append(
                f"intent_mismatch: expected translate, got {qp.get('intent')}"
            )
        if int(retrieval.get("clause_projections") or 0) < 1:
            chat_violations.append(
                "projection_not_injected: retrieval.clause_projections < 1"
            )
        if not any(s in answer for s in ANSWER_SIGNALS):
            chat_violations.append(
                "answer_lacks_clause_signal: no expected clause title/number in answer"
            )
        violations.extend(chat_violations)
        cases.append(
            {
                "id": "chat_translate_projection",
                "query": QUERY,
                "verdict": "fail" if chat_violations else "pass",
                "violations": chat_violations,
                "observed": {
                    "intent": qp.get("intent"),
                    "clause_projections": retrieval.get("clause_projections"),
                    "answer_excerpt": answer[:500],
                },
            }
        )
    except Exception as exc:
        status = "BLOCKED"
        violations = [f"blocked: {type(exc).__name__}: {exc}"]
        cases.append(
            {
                "id": "blocked",
                "verdict": "blocked",
                "violations": violations,
                "observed": {},
            }
        )

    if status != "BLOCKED":
        status = "FAIL" if any(c["verdict"] == "fail" for c in cases) else "PASS"

    summary = {
        "total": len(cases),
        "pass": sum(1 for c in cases if c["verdict"] == "pass"),
        "fail": sum(1 for c in cases if c["verdict"] == "fail"),
        "blocked": sum(1 for c in cases if c["verdict"] == "blocked"),
    }
    report = {
        "gate": "FD-CLAUSE",
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": args.base,
        "method": "DB clause_projection + Enclave wiki sync + live translate chat",
        "status": status,
        "contract_violations": violations,
        "elapsed_s": round(time.time() - t0, 1),
        "summary": summary,
        "cases": cases,
        "db": db_obs,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"status: {status} | summary: {json.dumps(summary)} | written: {OUT}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
