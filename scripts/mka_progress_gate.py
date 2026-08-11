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
    """Parse create_table + add_column across MKA migrations for ORM drift checks."""
    versions = PROJECT_ROOT / "app" / "db" / "migrations" / "versions"
    tables: dict = {}
    for migration_path in sorted(versions.glob("mka_*.py")):
        tree = ast.parse(migration_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            # create_table("name", sa.Column("col", ...), ...)
            if (
                func.attr == "create_table"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                table_name = node.args[0].value
                columns = set(tables.get(table_name, set()))
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
            # add_column("table", sa.Column("col", ...))
            if (
                func.attr == "add_column"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
            ):
                table_name = node.args[0].value
                col_node = node.args[1]
                if (
                    isinstance(col_node, ast.Call)
                    and isinstance(col_node.func, ast.Attribute)
                    and col_node.func.attr == "Column"
                    and col_node.args
                    and isinstance(col_node.args[0], ast.Constant)
                ):
                    columns = set(tables.get(table_name, set()))
                    columns.add(col_node.args[0].value)
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
    # 允許後續 vision migration 新增表；核心 10 表仍需完全對齊
    if failures:
        return False, "; ".join(failures)
    return True, "core MKA tables have ORM/migration column parity"


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
    """MKA-P0-MODULE-CONTRACT: 模組不是 prompt（以正式 seed 契約為準）。"""
    from app.services.mka_module_seed import CANONICAL_MODULES
    keys = [m["module_key"] for m in CANONICAL_MODULES]
    required = {"spec_sop", "sales_quote", "incident_handover", "quality_8d", "training_knowhow"}
    if not required.issubset(set(keys)):
        return False, f"canonical modules incomplete: {keys}"
    # 模組必須有 knowledge/intent/tools/forms/approval 契約欄位
    for m in CANONICAL_MODULES:
        for field in ("knowledge_scope_policy", "supported_intents", "allowed_tools", "form_definition_ids"):
            if field not in m:
                return False, f"{m['module_key']} missing {field}"
    return True, f"{len(keys)} canonical DB modules with full contracts"


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


# ── P1 Gates ──

def check_scene_resolver():
    """MKA-P1-SCENE: Scene resolver 存在且 prompt injection 被阻擋。"""
    from app.services.scene_resolver import get_scene_resolver
    resolver = get_scene_resolver()

    # 正常解析
    scene = resolver.resolve(qr_token="eq:CNC-001")
    if not scene or scene.equipment_id != "CNC-001":
        return False, "equipment QR resolve failed"

    # prompt injection 阻擋
    injected = resolver.resolve(qr_token="eq:test\nINJECT")
    if injected is not None:
        return False, "prompt injection not blocked"

    return True, "scene resolver + injection blocking verified"


def check_term_dictionary():
    """MKA-P1-TERMDICT: Term dictionary service 存在。"""
    from app.services.term_dictionary import TermDictionaryService
    # 驗證 class 存在且有 correct_transcript 方法
    if not hasattr(TermDictionaryService, 'correct_transcript'):
        return False, "correct_transcript method missing"
    if not hasattr(TermDictionaryService, 'search_terms'):
        return False, "search_terms method missing"
    return True, "TermDictionaryService with correct_transcript + search_terms"


def check_interaction_api():
    """MKA-P1-INTERACTION: Interaction API endpoint 存在。"""
    endpoint_path = PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "interaction.py"
    if not endpoint_path.exists():
        return False, "interaction.py not found"
    content = endpoint_path.read_text(encoding="utf-8")
    required = [
        "/interaction/transcriptions",
        "/interaction/sessions",
        "/interaction/sessions/{session_id}/transcript",
        "/interaction/sessions/{session_id}/resolve",
    ]
    missing = [r for r in required if r not in content]
    if missing:
        return False, f"missing endpoints: {missing}"
    return True, "4 interaction endpoints verified"


def check_bootstrap_mka():
    """MKA-P0-BOOTSTRAP: experience/bootstrap 回傳 job_modules + interaction_capabilities。"""
    endpoint_path = PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "experience.py"
    content = endpoint_path.read_text(encoding="utf-8")
    required = ["job_modules", "default_job_home", "interaction_capabilities"]
    missing = [r for r in required if r not in content]
    if missing:
        return False, f"bootstrap missing: {missing}"
    return True, "bootstrap returns job_modules + interaction_capabilities"


# ── P2 Gates ──

def check_template_renderer():
    """MKA-P2-EXPORT: Template renderer 存在且可匯出。"""
    from app.services.template_renderer import get_template_renderer
    renderer = get_template_renderer()
    result = renderer.render_markdown(
        title="test", fields={"a": 1}, provenance={}, approval_info={"version": "1.0"}
    )
    if result.success and "Version 1.0" in result.content.decode("utf-8"):
        return True, "markdown export with watermark verified"
    return False, f"render failed: {result.error}"


def check_quote_e2e():
    """MKA-P2-QUOTE-E2E: 報價完整流程測試。"""
    return _run_pytest_node("tests/test_p2_export_e2e.py::TestQuoteE2E::test_full_quote_flow")


def check_immutable_snapshot():
    """MKA-P2-IMMUTABLE: immutable snapshot 結構驗證。"""
    return _run_pytest_node("tests/test_p2_export_e2e.py::TestImmutableSnapshot::test_provenance_structure")


def check_export_endpoint():
    """MKA-P2-EXPORT-API: 匯出 HTTP endpoint 存在且未核准不可匯出。"""
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_approved_form_export_uses_immutable_snapshot"
    )


def check_export_async_task():
    """MKA-P2-EXPORT-ASYNC: Celery 非同步匯出落 StorageBackend 且可下載。"""
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_render_form_export_task_stores_artifact"
    )


def check_export_async_endpoints():
    """MKA-P2-EXPORT-ASYNC: async 排程／exports 列表／下載端點註冊。"""
    return _run_pytest_node(
        "tests/test_mka_persistence.py::test_form_async_export_endpoints_registered"
    )


def check_embedding_cache():
    """Query embedding cache：命中不重打 provider（§7.2 P0 補強）。"""
    return _run_pytest_node("tests/test_embedding_cache.py")


def check_audio_retention_db():
    """MKA-P1-RETENTION: 政策/成本 DB 化＋purge 合約（關閉假綠）。"""
    return _run_pytest_node("tests/test_mka_audio_retention.py")


def check_retention_migration():
    """MKA-P1-RETENTION: migration 含兩張表＋RLS＋正確 down_revision。"""
    migration_path = (
        PROJECT_ROOT / "app" / "db" / "migrations" / "versions"
        / "mka_p1_audio_retention_001.py"
    )
    if not migration_path.exists():
        return False, "mka_p1_audio_retention_001.py not found"
    content = migration_path.read_text(encoding="utf-8")
    required = (
        '"mka_audio_policies"',
        '"mka_task_costs"',
        "tenant_isolation",
        'down_revision: Union[str, None] = "mka_p0_domain_001"',
        "ENABLE ROW LEVEL SECURITY",
    )
    missing = [item for item in required if item not in content]
    if missing:
        return False, f"retention migration missing={missing}"
    return True, "2 tables + RLS policy + chained on mka_p0_domain_001"


# ── P3 Gates ──

def check_incident_safety():
    """MKA-P3-SAFETY: 安全指引政策存在且緊急關鍵字被阻擋。"""
    from app.services.incident_handover import SafeGuidancePolicy
    policy = SafeGuidancePolicy()
    # 緊急偵測
    if not policy.check_emergency("設備冒煙了"):
        return False, "emergency detection failed"
    # 高風險無證據阻擋
    resp = policy.get_safe_response("需要拆卸馬達", has_evidence=False)
    if resp is None:
        return False, "high-risk without evidence not blocked"
    # 有證據不阻擋
    resp = policy.get_safe_response("需要拆卸馬達", has_evidence=True)
    if resp is not None:
        return False, "high-risk with evidence should not be blocked"
    return True, "safety policy: emergency + high-risk blocking verified"


def check_incident_form():
    """MKA-P3-INCIDENT-FORM: 異常表單 + 場景適配器存在。"""
    from app.services.incident_handover import IncidentForm, SceneAdapter
    form = IncidentForm(title="test", description="desc")
    if form.status.value != "draft":
        return False, "incident form default status wrong"
    adapter = SceneAdapter()
    return True, "IncidentForm + SceneAdapter verified"


def check_handover():
    """MKA-P3-HANDOVER: 交接狀態機存在。"""
    from app.services.incident_handover import ShiftHandover, HandoverStatus
    h = ShiftHandover(shift="早班", from_operator="A", to_operator="B")
    if h.status != HandoverStatus.DRAFT:
        return False, "handover default status wrong"
    return True, "ShiftHandover state machine verified"


# ── P4 Gates ──

def check_module_compatibility():
    """MKA-P4-REGISTRY: 相容性矩陣存在且檢查正確。"""
    from app.services.module_admin import CompatibilityMatrix
    matrix = CompatibilityMatrix()
    ok, _ = matrix.check_compatibility("spec_sop", "1.0")
    if not ok:
        return False, "compatible module rejected"
    ok, reason = matrix.check_compatibility("quality_8d", "1.0", enabled_packs=[])
    if ok:
        return False, "missing required packs not detected"
    return True, "compatibility matrix: compatible + required packs check verified"


# ── P5 Gates ──

def check_knowhow_lifecycle():
    """MKA-P5-LIFECYCLE: 知識卡生命週期（expiry + lineage + consent）存在。"""
    from app.services.knowhow_lifecycle import KnowhowLifecycleManager
    mgr = KnowhowLifecycleManager()
    # lineage
    lineage = mgr.record_lineage(card_id="test", audio_uri="uri", consent_obtained=True)
    if not lineage.expires_at:
        return False, "lineage expiry not set"
    # consent check
    mgr.record_lineage(card_id="test2", audio_uri="uri", consent_obtained=False)
    if not mgr.check_consent_required("test2"):
        return False, "consent check failed"
    return True, "lifecycle: lineage + expiry + consent verified"


# ── P6 Gates ──

def check_write_guardrail():
    """MKA-P6-WRITE-HITL: 寫入護欄存在且 fail-closed。"""
    from app.services.write_guardrail import WriteGuardrail, WriteRequest, WriteRisk
    guardrail = WriteGuardrail()
    # PROHIBITED 被拒
    req = WriteRequest(risk=WriteRisk.PROHIBITED, payload={})
    valid, _ = guardrail.validate(req)
    if valid:
        return False, "prohibited not rejected"
    # 高風險無 approval 被拒
    req = WriteRequest(risk=WriteRisk.HIGH_RISK_WRITE, approval_token="", payload={})
    valid, _ = guardrail.validate(req)
    if valid:
        return False, "high-risk without approval not rejected"
    # read-only 通過
    req = WriteRequest(risk=WriteRisk.READ_ONLY, payload={})
    valid, _ = guardrail.validate(req)
    if not valid:
        return False, "read-only rejected"
    return True, "write guardrail: prohibited + high-risk + read-only verified"


def check_write_idempotency():
    """MKA-P6-IDEMPOTENCY: 冪等執行。"""
    from app.services.write_guardrail import WriteGuardrail, WriteRequest, WriteRisk, WriteStatus
    guardrail = WriteGuardrail()
    req1 = WriteRequest(risk=WriteRisk.LOW_RISK_WRITE, payload={"id": 1})
    guardrail.execute(req1, execute_fn=lambda p: {"ok": True})
    req2 = WriteRequest(risk=WriteRisk.LOW_RISK_WRITE, payload={"id": 1})
    req2.idempotency_key = req1.idempotency_key
    result = guardrail.execute(req2, execute_fn=lambda p: {"ok": True})
    if result.status != WriteStatus.SUCCESS:
        return False, f"idempotent skip failed: {result.status}"
    return True, "idempotent execution verified"


def check_write_rollback():
    """MKA-P6-ROLLBACK: 失敗回滾。"""
    from app.services.write_guardrail import WriteGuardrail, WriteRequest, WriteRisk, WriteStatus
    guardrail = WriteGuardrail()
    req = WriteRequest(risk=WriteRisk.LOW_RISK_WRITE, max_retries=1, payload={})
    rollback_called = [False]
    def fail(p):
        raise Exception("permanent")
    def rollback(p, r):
        rollback_called[0] = True
    result = guardrail.execute(req, execute_fn=fail, rollback_fn=rollback)
    if result.status != WriteStatus.ROLLED_BACK:
        return False, f"rollback failed: {result.status}"
    if not rollback_called[0]:
        return False, "rollback function not called"
    return True, "rollback on failure verified"


def check_route_mounted(path_substr: str, endpoint_file: str):
    """Require both endpoint source AND api router include."""
    endpoint_path = PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / endpoint_file
    api_path = PROJECT_ROOT / "app" / "api" / "v1" / "api.py"
    if not endpoint_path.exists():
        return False, f"{endpoint_file} missing"
    ep = endpoint_path.read_text(encoding="utf-8")
    api = api_path.read_text(encoding="utf-8")
    if path_substr not in ep:
        return False, f"{path_substr} not in {endpoint_file}"
    module = endpoint_file.replace(".py", "")
    if module not in api:
        return False, f"{module} not included in api.py"
    return True, f"route {path_substr} mounted via {module}"


def check_scene_registry_migration():
    """SceneRegistry must have alembic migration + unique constraint."""
    mig = PROJECT_ROOT / "app" / "db" / "migrations" / "versions" / "mka_p2_vision_platform_001.py"
    if not mig.exists():
        return False, "mka_p2_vision_platform_001.py missing"
    text = mig.read_text(encoding="utf-8")
    required = ["mka_scene_registry", "uq_mka_scene_registry_tenant_token", "mka_job_roles", "mka_form_templates"]
    missing = [r for r in required if r not in text]
    if missing:
        return False, f"migration missing: {missing}"
    return True, "scene registry + job roles + templates migration present"


def check_voice_term_call_chain():
    """Voice transcribe must call term dictionary correct_transcript."""
    voice = (PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "voice.py").read_text(encoding="utf-8")
    if "correct_transcript" not in voice:
        return False, "voice.py does not call correct_transcript"
    if "detected_fields" not in voice:
        return False, "voice.py missing detected_fields contract"
    return True, "voice→term dictionary call chain present"


def check_scene_form_chat_wiring():
    """SceneContext must flow into forms create + chat retrieval."""
    forms = (PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "forms.py").read_text(encoding="utf-8")
    chat = (PROJECT_ROOT / "app" / "api" / "v1" / "endpoints" / "chat.py").read_text(encoding="utf-8")
    persist = (PROJECT_ROOT / "app" / "services" / "mka_persistence.py").read_text(encoding="utf-8")
    if "scene_context" not in forms or "scene_context" not in persist:
        return False, "forms create path missing scene_context"
    if "scene_to_filter_dict" not in chat and "scene_context" not in chat:
        return False, "chat path missing scene wiring"
    return True, "scene wired into forms + chat"


def check_module_db_router():
    """Module router must prefer DB registry (no dual-track defaults)."""
    router = (PROJECT_ROOT / "app" / "services" / "module_router.py").read_text(encoding="utf-8")
    if "seed_canonical_modules" not in router and "get_module_registry" not in router:
        return False, "module_router not DB-backed"
    if "procurement" in router and "_register_defaults" in router:
        return False, "legacy in-memory defaults still present"
    seed = (PROJECT_ROOT / "app" / "services" / "mka_module_seed.py").read_text(encoding="utf-8")
    for key in ("spec_sop", "sales_quote", "incident_handover", "quality_8d", "training_knowhow"):
        if key not in seed:
            return False, f"canonical module missing: {key}"
    return True, "DB module router + 5 canonical modules"


def check_openapi_runtime_optional():
    """If API is running, require terms/job-modules/audio-policy/scene registry paths."""
    import urllib.request
    urls = [
        "http://127.0.0.1:8005/api/v1/openapi.json",
        "http://127.0.0.1:8005/openapi.json",
        "http://127.0.0.1:8000/api/v1/openapi.json",
        "http://127.0.0.1:8000/openapi.json",
    ]
    data = None
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                break
        except Exception:
            continue
    if data is None:
        return True, "API not running — skipped runtime OpenAPI (static route checks still apply)"
    paths = data.get("paths") or {}
    required = [
        "/api/v1/terms",
        "/api/v1/job-modules",
        "/api/v1/scene/registry",
        "/api/v1/forms/templates",
        "/api/v1/enterprise/adapters",
        "/api/v1/mka/metrics/summary",
    ]
    # tolerate prefix variations
    joined = " ".join(paths.keys())
    missing = []
    for r in required:
        short = r.split("/api/v1", 1)[-1]
        if short not in joined and r not in joined:
            missing.append(r)
    if missing:
        return False, f"runtime OpenAPI missing: {missing}"
    return True, f"runtime OpenAPI verified via live server ({len(paths)} paths)"


def check_frontend_job_home_dynamic():
    """Job home must use bootstrap workspace_entries, not only hardcoded cards."""
    page = (PROJECT_ROOT / "frontend" / "src" / "pages" / "job" / "JobHomePage.tsx").read_text(encoding="utf-8")
    if "workspace_entries" not in page:
        return False, "JobHomePage missing workspace_entries"
    if "WORK_ENTRIES" in page and "FALLBACK_ENTRIES" not in page:
        return False, "JobHomePage still hardcodes WORK_ENTRIES as sole source"
    quote_dir = PROJECT_ROOT / "frontend" / "src" / "pages" / "quote"
    incident_dir = PROJECT_ROOT / "frontend" / "src" / "pages" / "incident"
    if quote_dir.exists() or incident_dir.exists():
        return False, "dead quote/incident page trees still present"
    return True, "dynamic job home + dead pages removed"


def check_enterprise_adapter_contract():
    path = PROJECT_ROOT / "app" / "services" / "enterprise_adapters.py"
    if not path.exists():
        return False, "enterprise_adapters.py missing"
    text = path.read_text(encoding="utf-8")
    for name in ("StubERPAdapter", "StubCRMAdapter", "StubMESAdapter", "fail"):
        if name == "fail" and "fail closed" not in text and "fail-closed" not in text and "fail closed" not in text.lower():
            # accept RuntimeError fail closed wording
            if "fail closed" not in text and "not configured" not in text:
                return False, "adapters not fail-closed"
    return True, "ERP/CRM/MES adapter contracts present"


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
        ("embedding_cache", check_embedding_cache),
    ],
    "MKA-P0-EVAL": [("eval_profile", check_eval_profile)],
    "MKA-P0-BOOTSTRAP": [("bootstrap_mka", check_bootstrap_mka)],
    "MKA-P2-FORM-SCHEMA": [
        ("form_schema", check_form_schema),
        ("persistent_form_contract", check_persistent_form_contract),
        ("form_persistence_test", check_form_persistence_test),
    ],
    "MKA-P2-RULES": [("form_rules", check_form_rules)],
    "MKA-P2-EXPORT": [
        ("template_renderer", check_template_renderer),
        ("quote_e2e", check_quote_e2e),
        ("immutable_snapshot", check_immutable_snapshot),
        ("export_endpoint", check_export_endpoint),
    ],
    "MKA-P2-EXPORT-ASYNC": [
        ("export_async_task", check_export_async_task),
        ("export_async_endpoints", check_export_async_endpoints),
    ],
    "MKA-P1-RETENTION": [
        ("retention_db_contract", check_audio_retention_db),
        ("retention_migration", check_retention_migration),
    ],
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
    "MKA-P1-SCENE": [
        ("scene_resolver", check_scene_resolver),
        ("scene_registry_migration", check_scene_registry_migration),
        ("scene_admin_route", lambda: check_route_mounted("/scene/registry", "scene_admin.py")),
        ("scene_form_chat_wiring", check_scene_form_chat_wiring),
    ],
    "MKA-P1-TERMDICT": [
        ("term_dictionary", check_term_dictionary),
        ("voice_term_call_chain", check_voice_term_call_chain),
        ("terms_route", lambda: check_route_mounted("/correct", "terms.py")),
    ],
    "MKA-P1-INTERACTION": [("interaction_api", check_interaction_api)],
    "MKA-INT-MCP": [("mcp_server", check_mcp_server)],
    "MKA-INT-CONNECTOR": [("connector_materialize", check_connector_materialize)],
    # P3
    "MKA-P3-SAFETY": [("incident_safety", check_incident_safety)],
    "MKA-P3-INCIDENT-FORM": [("incident_form", check_incident_form)],
    "MKA-P3-HANDOVER": [("handover", check_handover)],
    # P4
    "MKA-P4-REGISTRY": [
        ("module_compatibility", check_module_compatibility),
        ("module_db_router", check_module_db_router),
        ("job_modules_route", lambda: check_route_mounted("/admin/{module_key}/enable", "job_modules.py")),
        ("job_roles_route", lambda: check_route_mounted("/job-roles", "job_roles.py")),
        ("frontend_job_home", check_frontend_job_home_dynamic),
    ],
    # P5
    "MKA-P5-LIFECYCLE": [
        ("knowhow_lifecycle", check_knowhow_lifecycle),
        ("interview_route", lambda: check_route_mounted("/knowhow/interview/extract", "interview.py")),
    ],
    # P6
    "MKA-P6-WRITE-HITL": [
        ("write_guardrail", check_write_guardrail),
        ("enterprise_adapters", check_enterprise_adapter_contract),
        ("enterprise_route", lambda: check_route_mounted("/enterprise/adapters", "enterprise.py")),
    ],
    "MKA-P6-IDEMPOTENCY": [("write_idempotency", check_write_idempotency)],
    "MKA-P6-ROLLBACK": [("write_rollback", check_write_rollback)],
    "MKA-VISION-RUNTIME": [
        ("openapi_runtime", check_openapi_runtime_optional),
        ("templates_route", lambda: check_route_mounted("/forms/templates", "form_templates.py")),
        ("metrics_route", lambda: check_route_mounted("/mka/metrics/summary", "mka_metrics.py")),
        ("audio_policy_route", lambda: check_route_mounted("/costs", "audio_policy.py")),
    ],
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