#!/usr/bin/env python
"""
MKA Gate Framework — 獨立進度語言。

對照 ENGINEERING_PLAN.md §10：
- 獨立 MKA-* 閘門，不改寫既有 Triple Injection 主計畫完成率
- make mka-gates
- scripts/mka_progress_gate.py
- artifacts/mka_*

Gate 分類（§10.2）：
- MKA-ACC-*   準確性、來源、拒答、欄位正確
- MKA-UX-*    任務完成、真機、無障礙、錯誤復原
- MKA-MOD-*   模組契約、ACL、版本、啟停
- MKA-FORM-*  schema、規則、provenance、輸出
- MKA-APPROVAL-* 簽核、冪等、immutable snapshot
- MKA-KH-*    know-how 草稿隔離與發布
- MKA-INT-*   外部整合
- MKA-DEPLOY-* 雲端/地端 parity
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


def get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def run_gate(gate_name: str, checks: list) -> dict:
    """執行單一 gate 的多個檢查。

    Args:
        gate_name: Gate 名稱（如 MKA-P0-MODULE-CONTRACT）
        checks: 檢查列表，每個是 (check_name, check_fn) tuple

    Returns:
        Gate 結果 dict
    """
    result = {
        "gate": gate_name,
        "status": "pass",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": get_git_sha(),
        "metrics": {},
        "failures": [],
        "evidence": [],
    }

    for check_name, check_fn in checks:
        try:
            passed, detail = check_fn()
            result["metrics"][check_name] = {"passed": passed, "detail": detail}
            if passed:
                result["evidence"].append(f"{check_name}: {detail}")
            else:
                result["failures"].append(f"{check_name}: {detail}")
                result["status"] = "fail"
        except Exception as exc:
            result["metrics"][check_name] = {"passed": False, "detail": str(exc)}
            result["failures"].append(f"{check_name}: {exc}")
            result["status"] = "fail"

    return result


# ── Gate 檢查函式 ──

def check_module_contract():
    """MKA-P0-MODULE-CONTRACT: 模組不是 prompt。"""
    from app.services.module_router import get_module_router
    router = get_module_router()
    modules = router.list_modules()
    if len(modules) >= 7:
        return True, f"{len(modules)} modules registered"
    return False, f"only {len(modules)} modules"


def check_module_acl():
    """MKA-P0-ACL: 每次檢索帶 AuthorizationContext。"""
    from app.services.module_router import get_module_router
    router = get_module_router()
    # 無 authz 時應回傳空
    modules = router.get_available_modules(authz=None)
    if modules == []:
        return True, "authz=None correctly returns empty"
    return False, "authz=None should return empty"


def check_retrieval():
    """MKA-P0-RETRIEVAL: Parent/Sibling/Context Fitting feature flags exist。"""
    from app.config import settings
    flags = [
        settings.PARENT_DOC_ENABLED,
        settings.SIBLING_EXPANSION_ENABLED,
        settings.CONTEXT_FITTING_ENABLED,
    ]
    # 全部應該是 bool
    if all(isinstance(f, bool) for f in flags):
        return True, f"flags={flags}"
    return False, "flags not bool"


def check_eval_profile():
    """MKA-P0-EVAL: Eval Profile 可載入。"""
    from app.eval import load_profile
    try:
        profile = load_profile("z3_blind")
        if profile.profile_hash:
            return True, f"profile={profile.name}, hash={profile.profile_hash}"
        return False, "no hash"
    except Exception as exc:
        return False, str(exc)


def check_form_schema():
    """MKA-P2-FORM-SCHEMA: Fixed Form schema 存在。"""
    from app.services.fixed_form import get_form_registry
    registry = get_form_registry()
    forms = registry.list_forms()
    if "quote" in forms:
        return True, f"forms={forms}"
    return False, "quote form missing"


def check_form_rules():
    """MKA-P2-RULES: 確定性計算引擎存在。"""
    from app.services.fixed_form import FixedFormCalculator, FormField, FieldType
    field = FormField(name="test", label="test", type=FieldType.AMOUNT,
                      calculated=True, formula="MULTIPLY(a, b)")
    result = FixedFormCalculator.calculate(field, {"a": 10, "b": 20})
    if result == 200.0:
        return True, "MULTIPLY(10,20)=200"
    return False, f"calculation wrong: {result}"


def check_approval():
    """MKA-APPROVAL: 簽核狀態機存在且冪等。"""
    from app.services.approval_state import ApprovalStateMachine, ApprovalState
    sm = ApprovalStateMachine(timeout_hours=24)
    from uuid import uuid4
    ctx = sm.create_request(
        tool_name="test", tool_risk="high_risk_write",
        actor_id=uuid4(), actor_name="test",
        action_summary="test",
    )
    sm.approve(ctx.request_id, approved_by="admin")
    sm.approve(ctx.request_id, approved_by="admin")  # 冪等
    if ctx.state == ApprovalState.APPROVED:
        return True, "idempotent approve works"
    return False, "approve failed"


def check_knowhow_draft_isolation():
    """MKA-KH-DRAFT-ISOLATION: draft 不可命中。"""
    from app.services.knowhow_card import KnowhowCardManager, KnowhowCardStatus
    mgr = KnowhowCardManager()
    card = mgr.create_draft("test", "summary", ["step1"])
    if not card.is_indexable:
        return True, "draft not indexable"
    return False, "draft should not be indexable"


def check_knowhow_conflict():
    """MKA-KH-CONFLICT: SOP 衝突檢查存在。"""
    from app.services.sop_conflict import SOPConflictChecker, AuthorityTier
    if AuthorityTier.SOP > AuthorityTier.APPROVED_KNOWHOW:
        return True, "SOP > Approved Know-how"
    return False, "authority tier wrong"


def check_mcp_server():
    """MKA-INT-MCP: Read-only MCP server 存在。"""
    from app.services.mcp_server import get_mcp_server
    server = get_mcp_server()
    tools = server.list_tools()
    if all(t.read_only for t in tools):
        return True, f"{len(tools)} read-only tools"
    return False, "non-read-only tool found"


def check_connector_materialize():
    """MKA-INT-CONNECTOR: Connector materialize 下載器存在。"""
    from app.services.connector_materialize import ResourceDownloader
    dl = ResourceDownloader()
    if dl._is_remote_uri("https://example.com/file.pdf"):
        return True, "remote URI detection works"
    return False, "URI detection failed"


# ── Gate 定義 ──

GATES = {
    "MKA-P0-MODULE-CONTRACT": [("module_contract", check_module_contract)],
    "MKA-P0-ACL": [("module_acl", check_module_acl)],
    "MKA-P0-RETRIEVAL": [("retrieval_flags", check_retrieval)],
    "MKA-P0-EVAL": [("eval_profile", check_eval_profile)],
    "MKA-P2-FORM-SCHEMA": [("form_schema", check_form_schema)],
    "MKA-P2-RULES": [("form_rules", check_form_rules)],
    "MKA-APPROVAL-IDEMPOTENT": [("approval_idempotent", check_approval)],
    "MKA-KH-DRAFT-ISOLATION": [("draft_isolation", check_knowhow_draft_isolation)],
    "MKA-KH-CONFLICT": [("sop_conflict", check_knowhow_conflict)],
    "MKA-INT-MCP": [("mcp_server", check_mcp_server)],
    "MKA-INT-CONNECTOR": [("connector_materialize", check_connector_materialize)],
}


def main() -> int:
    ap = argparse.ArgumentParser(description="MKA Progress Gate")
    ap.add_argument("--gate", help="只跑特定 gate")
    ap.add_argument("--all", action="store_true", help="跑全部 gates")
    args = ap.parse_args()

    if not args.gate and not args.all:
        ap.print_help()
        return 1

    gates_to_run = [args.gate] if args.gate else list(GATES.keys())
    all_passed = True
    results = {}

    for gate_name in gates_to_run:
        if gate_name not in GATES:
            print(f"Unknown gate: {gate_name}")
            all_passed = False
            continue

        result = run_gate(gate_name, GATES[gate_name])
        results[gate_name] = result

        status_icon = "✅" if result["status"] == "pass" else "❌"
        print(f"{status_icon} {gate_name}: {result['status']}")
        for f in result["failures"]:
            print(f"   FAIL: {f}")

        if result["status"] != "pass":
            all_passed = False

        # 寫 artifact
        artifact_path = ARTIFACTS_DIR / f"mka_{gate_name.lower()}_last_run.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # 總結
    summary = {
        "total": len(gates_to_run),
        "passed": sum(1 for r in results.values() if r["status"] == "pass"),
        "failed": sum(1 for r in results.values() if r["status"] != "pass"),
        "gates": {k: v["status"] for k, v in results.items()},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": get_git_sha(),
    }
    summary_path = ARTIFACTS_DIR / "mka_progress_summary_last_run.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"MKA Gates: {summary['passed']}/{summary['total']} passed")
    if all_passed:
        print("ALL PASSED ✅")
    else:
        print("SOME FAILED ❌")
    print(f"Summary: {summary_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())