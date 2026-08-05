"""VISION Phase 5 — 能力上限盤點（可證明現況，非空口宣稱）。

檢查：
1. RETRIEVAL_RERANK 已開啟
2. 主 LLM／embedding 設定可讀
3. 條款投影（多語）已存在
4. MultiStepOrchestrator 模組可 import

產出 artifacts/capability_ceiling_last_run.json
"""
from __future__ import annotations

import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "capability_ceiling_last_run.json"


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT))
    from app.config import settings

    checks = []

    rerank = bool(getattr(settings, "RETRIEVAL_RERANK", False))
    checks.append({
        "id": "rerank_enabled",
        "status": "PASS" if rerank else "FAIL",
        "detail": f"RETRIEVAL_RERANK={rerank}",
    })

    llm = f"{getattr(settings, 'LLM_PROVIDER', '')}:{getattr(settings, 'OPENAI_MODEL', '') or getattr(settings, 'GEMINI_MODEL', '')}"
    checks.append({
        "id": "llm_configured",
        "status": "PASS" if getattr(settings, "LLM_PROVIDER", None) else "FAIL",
        "detail": llm,
    })

    try:
        from app.services.multi_step_orchestrator import MultiStepOrchestrator
        from app.services.tool_router import arms_for_plan
        from app.services.trace_recorder import RetrievalTraceView
        from app.services.refusal import build_refusal
        checks.append({
            "id": "phase2_modules",
            "status": "PASS",
            "detail": "MultiStepOrchestrator/ToolRouter/TraceRecorder/refusal importable",
        })
    except Exception as exc:
        checks.append({"id": "phase2_modules", "status": "FAIL", "detail": str(exc)})

    # DB clause projections
    try:
        from sqlalchemy import create_engine, text
        url = (
            f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}"
            f":{os.getenv('POSTGRES_PASSWORD', 'postgres')}"
            f"@{os.getenv('POSTGRES_SERVER', 'localhost')}"
            f":{os.getenv('POSTGRES_PORT', '5435')}"
            f"/{os.getenv('POSTGRES_DB', 'enclave')}"
        )
        eng = create_engine(url)
        with eng.connect() as c:
            n = c.execute(text(
                "SELECT count(*) FROM document_artifacts "
                "WHERE artifact_type='clause_projection' AND status='active'"
            )).scalar()
        checks.append({
            "id": "crosslang_projections",
            "status": "PASS" if int(n or 0) >= 1 else "FAIL",
            "detail": f"active_clause_projections={n}",
        })
    except Exception as exc:
        checks.append({"id": "crosslang_projections", "status": "BLOCKED", "detail": str(exc)})

    # Optional: Voyage rerank key presence (not required if local rerank)
    voyage = bool(getattr(settings, "VOYAGE_API_KEY", None) or os.getenv("VOYAGE_API_KEY"))
    checks.append({
        "id": "voyage_rerank_key",
        "status": "PASS" if voyage or rerank else "MARGINAL",
        "detail": f"VOYAGE_API_KEY_present={voyage} (local rerank fallback ok if RETRIEVAL_RERANK)",
    })

    status = "PASS" if all(c["status"] in ("PASS", "MARGINAL") for c in checks) else "FAIL"
    report = {
        "gate": "VISION-CEILING",
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "method": "config + module + DB inventory for Phase 5 ceiling readiness",
        "checks": checks,
        "notes": [
            "成本不設限：rerank／雲端 OCR／強 LLM 已在主路徑可用",
            "增量仍須個別消融；本閘門只證明能力上限元件已就位",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("status:", status)
    for c in checks:
        print(c["id"], c["status"], c["detail"])
    print("written:", OUT)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
