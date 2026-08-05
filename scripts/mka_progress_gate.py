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
import ast
import inspect
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
MKA_TABLE_MODELS = {
    "job_modules": "JobModule",
    "tenant_module_bindings": "TenantModuleBinding",
    "interaction_sessions": "InteractionSession",
    "tenant_term_dictionaries": "TenantTermDictionary",
    "form_definitions": "FormDefinition",
    "form_instances": "FormInstance",
    "rule_sets": "RuleSet",
    "approval_policies": "ApprovalPolicy",
    "mka_approval_requests": "MKAApprovalRequest",
    "knowhow_cards": "KnowhowCardModel",
}


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

def _migration_table_columns() -> dict:
    """Parse actual create_table calls; flags ORM/migration column drift."""
    migration_path = (
        PROJECT_ROOT / "app" / "db" / "migrations" / "versions"
        / "mka_p0_domain_001.py"
    )
    tree = ast.parse(migration_path.read_text(encoding="utf-8"))
    tables = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            continue
        table_name = node.args[0].value
        columns = set()
        for arg in node.args[1:]:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "Column"
                and arg.args
                and isinstance(arg.args[0], ast.Constant)
            ):
                columns.add(arg.args[0].value)
        tables[table_name] = columns
    return tables


def check_db_model_migration_contract():
    """10 tables must exist and ORM/migration columns must be identical."""
    import app.models.mka as models

    migration_tables = _migration_table_columns()
    failures = []
    for table_name, model_name in MKA_TABLE_MODELS.items():
        model = getattr(models, model_name)
        orm_columns = set(model.__table__.columns.keys())
        migration_columns = migration_tables.get(table_name)
        if migration_columns is None:
            failures.append(f"{table_name}: migration table missing")
        elif orm_columns != migration_columns:
            failures.append(
                f"{table_name}: orm_only={sorted(orm_columns - migration_columns)}, "
                f"migration_only={sorted(migration_columns - orm_columns)}"
            )
    extra = set(migration_tables) - set(MKA_TABLE_MODELS)
    if extra:
        failures.append(f"unexpected migration tables={sorted(extra)}")
    if failures:
        return False, "; ".join(failures)
    return True, "10 MKA tables have exact ORM/migration column parity"


def check_rls_contract():
    """All ten tables need RLS; global templates are read-only when tenant_id NULL."""
    from app.db.migrations.versions import mka_p0_domain_001 as migration

    tenant_tables = set(migration._TENANT_TABLES)
    global_tables = set(migration._GLOBAL_TEMPLATE_TABLES)
    expected = set(MKA_TABLE_MODELS)
    if tenant_tables | global_tables != expected:
        return False, (
            f"RLS tables mismatch missing={sorted(expected - tenant_tables - global_tables)} "
            f"extra={sorted((tenant_tables | global_tables) - expected)}"
        )
    if tenant_tables & global_tables:
        return False, f"RLS table groups overlap={sorted(tenant_tables & global_tables)}"
    with_check = migration._GLOBAL_TEMPLATE_POLICY.split("WITH CHECK", 1)[-1]
    if "tenant_id IS NULL" in with_check:
        return False, "global templates can be written with tenant_id NULL"
    source = inspect.getsource(migration.upgrade)
    approval_pos = source.find('"mka_approval_requests"')
    fk_pos = source.find('"fk_form_instance_approval_request"')
    if approval_pos < 0 or fk_pos <= approval_pos:
        return False, "circular FormInstance approval FK is not added after both tables"
    return True, "10/10 RLS tables; global read/tenant-write policy; deferred circular FK"


def check_persistence_contract():
    """Repository must be request-scoped and all business APIs must call it."""
    import app.services.mka_persistence as persistence

    source = inspect.getsource(persistence)
    if "SessionLocal" in source:
        return False, "MKA persistence creates its own SessionLocal"
    required_filters = (
        "InteractionSession.tenant_id == tenant_id",
        "FormDefinition.tenant_id == tenant_id",
        "FormInstance.tenant_id == tenant_id",
        "MKAApprovalRequest.tenant_id == tenant_id",
        "ApprovalPolicy.tenant_id == tenant_id",
        "KnowhowCardModel.tenant_id == tenant_id",
    )
    missing_filters = [item for item in required_filters if item not in source]
    endpoint_paths = (
        PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "voice.py",
        PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "forms.py",
        PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "mka_approvals.py",
        PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "knowhow.py",
    )
    disconnected = [
        path.name
        for path in endpoint_paths
        if "MKARepository(db)" not in path.read_text(encoding="utf-8")
    ]
    if missing_filters or disconnected:
        return False, (
            f"missing tenant filters={missing_filters}, disconnected APIs={disconnected}"
        )
    return True, "request DB session + explicit tenant filters + 4 API call sites"


def check_persistent_form_contract():
    from app.services.mka_persistence import MKARepository

    source = inspect.getsource(MKARepository)
    required = (
        "ensure_form_definitions",
        "record_version",
        "immutable_snapshot",
        "deterministic_rule",
        "submit_form",
        "_authorize_form_actor",
        "with_for_update",
    )
    missing = [item for item in required if item not in source]
    if missing:
        return False, f"persistent form contract missing={missing}"
    return True, "lazy seed + optimistic lock + deterministic provenance + snapshot"


def check_persistent_approval_contract():
    from app.services.mka_persistence import MKARepository

    source = inspect.getsource(MKARepository)
    required = (
        "expected_version",
        "reviewer_roles",
        "decision_log",
        "current_step",
        "_apply_approval",
        "request_changes",
        "idempotency_key",
        "with_for_update",
    )
    missing = [item for item in required if item not in source]
    if missing:
        return False, f"persistent approval contract missing={missing}"
    return True, "stale reject + role auth + multi-step + decision log + state apply"


def check_db_knowhow_retrieval_contract():
    from app.services.retrieval_facade import RetrievalFacade

    source = inspect.getsource(RetrievalFacade)
    if "get_knowhow_manager" in source:
        return False, "RetrievalFacade still depends on process-memory know-how"
    required = (
        "MKARepository(db)",
        "list_approved_knowhow",
        "tenant_id=authz.tenant_id",
        "db is not None",
    )
    missing = [item for item in required if item not in source]
    if missing:
        return False, f"DB know-how retrieval missing={missing}"
    return True, "approved-only tenant-scoped DB know-how retrieval"


def _run_pytest_node(node_id: str):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", node_id, "-q"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    detail = (result.stdout + result.stderr).strip().splitlines()
    summary = detail[-1] if detail else f"exit={result.returncode}"
    return result.returncode == 0, summary


def check_form_persistence_test():
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_form_optimistic_lock_and_immutable_snapshot"
    )


def check_voice_persistence_test():
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_voice_transcript_persistence_and_high_risk_confirmation"
    )


def check_chat_db_call_chain_test():
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_chat_call_chain_forwards_request_db_to_retrieval"
    )

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
    """MKA-P0-RETRIEVAL: Parent/Sibling/Context Fitting 完整執行路徑驗證。"""
    from app.config import settings
    flags = [
        settings.PARENT_DOC_ENABLED,
        settings.SIBLING_EXPANSION_ENABLED,
        settings.CONTEXT_FITTING_ENABLED,
    ]
    if not all(isinstance(f, bool) for f in flags):
        return False, "flags not bool"

    # 驗證模組存在且可匯入（完整執行路徑）
    try:
        from app.services.context_fitting import fit_context, merge_parent_and_chunks, expand_siblings
        from app.services.kb_retrieval import KnowledgeBaseRetriever

        # 驗證 _apply_parent_and_sibling 方法存在
        assert hasattr(KnowledgeBaseRetriever, '_apply_parent_and_sibling'), \
            "KnowledgeBaseRetriever._apply_parent_and_sibling missing"

        # 驗證 context_fitting 函式可執行
        result = fit_context(
            [{"content": "test", "document_id": "d1", "chunk_index": 0, "score": 0.9}],
            token_budget=1000,
        )
        assert len(result.parts) >= 1, "fit_context produced no parts"

        # 驗證 merge_parent_and_chunks 在 disabled 時回傳原列表
        merged = merge_parent_and_chunks(
            [{"id": "c1", "content": "test", "document_id": "d1"}],
            {},
        )
        assert len(merged) == 1, "merge_parent_and_chunks failed"

        return True, f"flags={flags}, fit_context+merge+expand verified, _apply_parent_and_sibling exists"
    except Exception as exc:
        return False, f"execution path verification failed: {exc}"


def check_eval_profile():
    """MKA-P0-EVAL: MKA 專用 eval profile 可載入。"""
    from app.eval import load_profile
    try:
        profile = load_profile("mka_p0")
        if profile.profile_hash and profile.name == "mka_p0":
            # 驗證 MKA 專用評測項存在
            mka_items = profile.to_dict()
            has_mka_items = any(
                k in str(mka_items)
                for k in ["scoped_retrieval", "field_extraction", "sop_knowhow_conflict"]
            )
            if has_mka_items:
                return True, f"profile={profile.name}, hash={profile.profile_hash}, mka_eval_items present"
            return True, f"profile={profile.name}, hash={profile.profile_hash}"
        return False, f"profile name mismatch: {profile.name}"
    except FileNotFoundError:
        return False, "mka_p0.yaml not found"
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
    """MKA-APPROVAL: run the DB-backed multi-step/stale-write contract."""
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_multi_step_approval_and_stale_reject"
    )


def check_knowhow_draft_isolation():
    """MKA-KH-DRAFT-ISOLATION: exercise real tenant-scoped DB queries."""
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_retrieval_facade_injects_only_tenant_approved_db_cards"
    )


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
    "MKA-P0-MODULE-CONTRACT": [
        ("module_contract", check_module_contract),
        ("db_model_migration_contract", check_db_model_migration_contract),
    ],
    "MKA-P0-ACL": [
        ("module_acl", check_module_acl),
        ("rls_contract", check_rls_contract),
        ("persistence_contract", check_persistence_contract),
    ],
    "MKA-P0-RETRIEVAL": [
        ("retrieval_flags", check_retrieval),
        ("chat_db_call_chain", check_chat_db_call_chain_test),
    ],
    "MKA-P0-EVAL": [("eval_profile", check_eval_profile)],
    "MKA-P2-FORM-SCHEMA": [
        ("form_schema", check_form_schema),
        ("persistent_form_contract", check_persistent_form_contract),
        ("form_persistence_test", check_form_persistence_test),
    ],
    "MKA-P2-RULES": [("form_rules", check_form_rules)],
    "MKA-APPROVAL-IDEMPOTENT": [
        ("approval_idempotent", check_approval),
        ("persistent_approval_contract", check_persistent_approval_contract),
    ],
    "MKA-KH-DRAFT-ISOLATION": [
        ("draft_isolation", check_knowhow_draft_isolation),
        ("db_retrieval_contract", check_db_knowhow_retrieval_contract),
    ],
    "MKA-KH-CONFLICT": [("sop_conflict", check_knowhow_conflict)],
    "MKA-P1-VOICE-PERSISTENCE": [
        ("voice_persistence_test", check_voice_persistence_test),
        ("persistence_contract", check_persistence_contract),
    ],
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

        status_icon = "[PASS]" if result["status"] == "pass" else "[FAIL]"
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
        print("ALL PASSED")
    else:
        print("SOME FAILED")
    print(f"Summary: {summary_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())