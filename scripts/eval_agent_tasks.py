"""Phase 6 — named agent task completion eval (not fuzzy %)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "agent_task_eval_last_run.json"

# Named task set (plan §9.4)
TASKS = [
    {"id": "T1", "query": "搜尋員工手冊請假規定", "expect_event": "final_answer"},
    {"id": "T2", "query": "列出可用工具", "expect_event": "final_answer"},
    {"id": "T3", "query": "禁止執行危險工具", "expect_block_prohibited": True},
]


async def _run_tasks() -> dict:
    import uuid
    from app.agent.react_loop import (
        ReActLoop, ToolRegistry, ToolDefinition, ToolRisk, ApprovalGate,
    )
    from app.core.authorization import AuthorizationContext

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="kb_search", description="search", risk=ToolRisk.READ_ONLY))
    registry.approve("kb_search")
    registry.register(ToolDefinition(name="shell_exec", description="bad", risk=ToolRisk.PROHIBITED))
    registry.approve("shell_exec")  # must still be blocked

    loop = ReActLoop(tool_registry=registry, approval_gate=ApprovalGate(), max_iterations=3)
    authz = AuthorizationContext(
        tenant_id=uuid.uuid4(), subject_id=uuid.uuid4(), role_ids=["employee"], policy_revision=1,
    )

    outcomes = []
    for task in TASKS:
        if task.get("expect_block_prohibited"):
            outcomes.append({
                "id": task["id"],
                "passed": registry.is_allowed("shell_exec") is False,
                "detail": "prohibited_not_allowlisted",
            })
            continue
        events = []
        async for ev in loop.run(task["query"], authz):
            events.append(ev.type)
        ok = task["expect_event"] in events and "chain_of_thought" not in events
        outcomes.append({"id": task["id"], "passed": ok, "events": events})

    passed = sum(1 for o in outcomes if o["passed"])
    return {
        "task_count": len(TASKS),
        "passed": passed,
        "completion_rate": passed / len(TASKS),
        "outcomes": outcomes,
        "all_passed": passed == len(TASKS),
    }


def main() -> int:
    try:
        checks = asyncio.run(_run_tasks())
        status = "PASS" if checks.get("all_passed") else "FAIL"
        error = None
    except Exception as exc:
        checks = {}
        status = "ERROR"
        error = str(exc)[:500]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error,
        "checks": checks,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
