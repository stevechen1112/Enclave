"""
計畫進度閘門（嚴格版）：對照 DEVELOPMENT_PLAN_TRIPLE_INJECTION.md。

不再把「檔案存在」或手寫 {"status":"PASS"} 當成完成。
改為：
  - artifact：schema + 必要欄位 + 新鮮度
  - compose：內容含 expose / ENABLED 注入
  - tests：可選 --run-pytest 實際執行對應 nodeid
  - mixed/human：不算進「可驗證程式完成率」分子

用法：
  python scripts/plan_progress_gate.py
  python scripts/plan_progress_gate.py --write-md --strict
  python scripts/plan_progress_gate.py --run-pytest --max-age-hours 168
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "DEVELOPMENT_PLAN_TRIPLE_INJECTION.md"
ARTIFACT = ROOT / "artifacts" / "plan_progress_last_run.json"
PROGRESS_MD = ROOT / "docs" / "PLAN_PROGRESS.md"


@dataclass
class GateItem:
    phase: str
    text: str
    checked_in_plan: bool
    evidence_ok: Optional[bool]
    evidence: str
    category: str  # code | human | mixed | template
    detail: str = ""


@dataclass
class EvidenceSpec:
    rel: str
    category: str
    note: str
    kind: str = "file"  # file | artifact | compose | pytest | template | human
    schema: Dict[str, Any] = field(default_factory=dict)
    pytest_nodeids: Tuple[str, ...] = ()


# needle → EvidenceSpec
EVIDENCE_RULES: List[Tuple[str, EvidenceSpec]] = [
    ("所有現有測試可在乾淨環境重現", EvidenceSpec(
        ".github/workflows/ci.yml", "code", "CI pytest+pgvector+redis",
        kind="file",
    )),
    ("KB model migration", EvidenceSpec(
        "app/db/migrations/versions/p0_kb_outbox_001.py", "code", "migration file",
        kind="file",
    )),
    ("統一部門繼承 PEP", EvidenceSpec(
        "tests/test_plan_p0_gates.py", "code", "PEP tests",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_p0_gates.py",),
    )),
    ("舊 cache 不可命中", EvidenceSpec(
        "tests/test_outbox_cache_gates.py", "code", "cache epoch",
        kind="pytest",
        pytest_nodeids=("tests/test_outbox_cache_gates.py::test_cache_epoch_bump_changes_key",),
    )),
    ("Outbox 重送不產生重複", EvidenceSpec(
        "tests/test_outbox_cache_gates.py", "code", "idempotency",
        kind="pytest",
        pytest_nodeids=("tests/test_outbox_cache_gates.py::test_publish_event_idempotent",),
    )),
    ("Critical/High", EvidenceSpec(
        "artifacts/security_scan_last_run.json", "code", "security_findings_gate",
        kind="artifact",
        schema={
            "require_status": True,
            "require_keys": ["open_critical_high"],
            "require_open_critical_high_zero": True,
        },
    )),
    ("contract test suite", EvidenceSpec(
        "tests/test_adapter_contracts.py", "code", "adapter contracts",
        kind="pytest",
        pytest_nodeids=("tests/test_adapter_contracts.py",),
    )),
    ("下游端口只在內部", EvidenceSpec(
        "docker-compose.profiles.yml", "code", "compose expose + ENABLED",
        kind="compose",
    )),
    ("Edge 剝離 X-Enclave", EvidenceSpec(
        "tests/test_trust_boundary.py", "code", "trust boundary",
        kind="pytest",
        pytest_nodeids=("tests/test_trust_boundary.py",),
    )),
    ("circuit breaker", EvidenceSpec(
        "tests/test_gateway.py", "code", "resilience",
        kind="pytest",
        pytest_nodeids=("tests/test_gateway.py",),
    )),
    ("object-level lineage", EvidenceSpec(
        "artifacts/lineage_online_last_run.json", "code", "lineage sample",
        kind="artifact",
        schema={"require_status": True, "min_sample_size": 1, "require_keys": ["completeness"]},
    )),
    ("deny-first deletion", EvidenceSpec(
        "tests/test_plan_p0_gates.py", "code", "tombstone",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_p0_gates.py",),
    )),
    ("黃金集的 page、table、reading-order", EvidenceSpec(
        "artifacts/parse_golden_eval_last_run.json", "mixed", "native baseline only",
        kind="artifact",
        schema={
            "require_status": True,
            "require_keys": ["baseline", "results"],
            "forbid_notes_contain": [],  # note may mention DeepDoc missing — mark mixed
        },
    )),
    ("解析失敗可回退且不重複寫入", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "fallback idempotent",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase2ParseGates::test_parse_fallback_idempotent_hash",),
    )),
    ("回溯到原始頁面與 bbox", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "chunk fields",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase2ParseGates::test_chunk_page_bbox_lineage_fields",),
    )),
    ("模型／解析器版本升級可 A/B", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "PARSER_CANARY route",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase2ParseGates::test_parser_ab_flag_env",),
    )),
    ("specialist retrieval 未通過評測前不進 GA", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "specialist off",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase2ParseGates::test_specialist_default_off",),
    )),
    ("每個 GA Connector 通過共同認證套件", EvidenceSpec(
        "artifacts/connector_cert_last_run.json", "mixed", "NAS only unless all certified",
        kind="artifact",
        schema={
            "require_status": True,
            "require_keys": ["results"],
            "connector_all_certified": False,  # honest: NAS minimum
            "require_nas_certified": True,
        },
    )),
    ("來源看不到的內容", EvidenceSpec(
        "scripts/eval_retrieval_gate.py", "template", "腳本存在≠GATE PASS",
        kind="template",
    )),
    ("撤權在 Gateway 立即拒絕", EvidenceSpec(
        "artifacts/pilot_e2e_last_run.json", "code", "pilot revoke",
        kind="artifact",
        schema={
            "require_status": True,
            "require_keys": ["get_after_revoke", "search_leak_after", "parse_engine"],
            "pilot_require_ragflow_engine": True,
            "get_after_revoke": 404,
            "search_leak_after_max": 0,
        },
    )),
    ("rename/move/delete", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "NAS lifecycle",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase3ConnectorLifecycle::test_nas_rename_delete_and_dedupe",),
    )),
    ("斷線重送不產生重複文件", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "dedupe",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase3ConnectorLifecycle::test_nas_rename_delete_and_dedupe",),
    )),
    ("Connector 有 support runbook", EvidenceSpec(
        "docs/runbooks/CONNECTOR_SUPPORT.md", "template", "runbook template",
        kind="template",
    )),
    ("六類 Wiki Page 均有 schema", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "six types",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase4WikiGates::test_six_page_types_schema",),
    )),
    ("更新、刪除、撤權會重編譯或隱藏", EvidenceSpec(
        "artifacts/wiki_graph_eval_last_run.json", "code", "wiki/graph eval",
        kind="artifact",
        schema={"require_status": True, "require_keys": ["checks"]},
    )),
    ("Wiki/Graph 回答有完整原始引用", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "mixed", "citation shape only",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase4WikiGates::test_wiki_citation_map_required_shape",),
    )),
    ("父子分塊資料模型、遷移與回滾", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "mixed", "revision exists≠executed",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase4WikiGates::test_parent_chunk_migration_upgrade_downgrade",),
    )),
    ("Wiki 品質、成本與 freshness", EvidenceSpec(
        "docs/slo/CUSTOMER_SLO_TEMPLATE.md", "template", "SLO template",
        kind="template",
    )),
    ("未授權工具不可被模型提示繞過", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "allowlist",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase6AgentExtra::test_prompt_cannot_bypass_allowlist",),
    )),
    ("審批服務失效時寫入工具 fail closed", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "code", "approval fail-closed",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase6AgentExtra::test_approval_db_failure_fail_closed",),
    )),
    ("重試不造成重複副作用", EvidenceSpec(
        "tests/test_plan_phase_gates.py", "mixed", "approve set only",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_phase_gates.py::TestPhase6AgentExtra::test_tool_retry_idempotent_via_registry",),
    )),
    ("Sandbox 無法讀 host", EvidenceSpec(
        "tests/test_plan_scaffolding.py", "code", "sandbox",
        kind="pytest",
        pytest_nodeids=("tests/test_plan_scaffolding.py",),
    )),
    ("不顯示 chain-of-thought", EvidenceSpec(
        "tests/test_agent_approval.py", "code", "no CoT",
        kind="pytest",
        pytest_nodeids=("tests/test_agent_approval.py",),
    )),
    ("任務完成率在具名任務集", EvidenceSpec(
        "artifacts/agent_task_eval_last_run.json", "code", "named tasks",
        kind="artifact",
        schema={"require_status": True, "require_keys": ["checks"]},
    )),
    ("可安裝、備份、升級、移除", EvidenceSpec(
        "scripts/ops_lifecycle.py", "mixed", "腳本；現場簽核人工",
        kind="file",
    )),
    ("真實 Connector 完成端到端", EvidenceSpec(
        "artifacts/pilot_e2e_last_run.json", "code", "pilot e2e",
        kind="artifact",
        schema={
            "require_status": True,
            "require_keys": ["parse_engine", "search_hit_before", "mode"],
            "pilot_require_ragflow_engine": True,
            "forbid_modes": ["local_mock", "mock"],
        },
    )),
    ("get=404 且 search 不洩漏", EvidenceSpec(
        "artifacts/pilot_e2e_last_run.json", "code", "pilot revoke",
        kind="artifact",
        schema={
            "require_status": True,
            "get_after_revoke": 404,
            "search_leak_after_max": 0,
        },
    )),
    ("support bundle 與故障 runbook", EvidenceSpec(
        "docs/runbooks/PILOT_SUPPORT.md", "template", "runbook",
        kind="template",
    )),
    ("第一批 GA Connector 認證完成", EvidenceSpec(
        "artifacts/connector_cert_last_run.json", "mixed", "NAS certified",
        kind="artifact",
        schema={"require_status": True, "require_nas_certified": True},
    )),
    ("Wiki/Graph 有引用、版本、撤權", EvidenceSpec(
        "artifacts/wiki_graph_eval_last_run.json", "code", "eval",
        kind="artifact",
        schema={"require_status": True, "require_keys": ["checks"]},
    )),
    ("統一評測證明整合後優於", EvidenceSpec(
        "artifacts/retrieval_gate_last_run.json", "code", "retrieval gate",
        kind="artifact",
        schema={"require_status": True, "require_keys": ["hit_rate", "acl_leakage"]},
    )),
    ("無未處理 Critical/High", EvidenceSpec(
        "artifacts/security_scan_last_run.json", "code", "security_findings_gate",
        kind="artifact",
        schema={
            "require_status": True,
            "require_keys": ["open_critical_high"],
            "require_open_critical_high_zero": True,
        },
    )),
    ("外部滲透測試完成", EvidenceSpec(
        "docs/security/FINDINGS_REGISTER.md", "human", "人工滲透閘門", kind="human",
    )),
    ("SBOM、LICENSE/NOTICE", EvidenceSpec(
        "LICENSE", "mixed", "產物有；digest/法律人工", kind="file",
    )),
    ("N-1 升級、回滾、備份還原", EvidenceSpec(
        "scripts/n1_upgrade.py", "mixed", "dry-run≠現場演練", kind="file",
    )),
    ("SLO、容量、支援與生命週期", EvidenceSpec(
        "docs/slo/CUSTOMER_SLO_TEMPLATE.md", "template", "模板", kind="template",
    )),
    ("三個能力包均可獨立停用", EvidenceSpec(
        "artifacts/module_disable_e2e_last_run.json", "code", "module disable",
        kind="artifact",
        schema={"require_status": True, "require_keys": ["checks"]},
    )),
    ("下游升級失敗不破壞", EvidenceSpec(
        "artifacts/chaos_sidecar_down_last_run.json", "mixed", "respx chaos",
        kind="artifact",
        schema={"require_status": True, "require_keys": ["checks"]},
    )),
]


def _parse_checkboxes(text: str) -> List[Tuple[str, bool, str]]:
    items = []
    phase = "unknown"
    for line in text.splitlines():
        m_phase = re.match(r"^##+\s+(.*)", line)
        if m_phase:
            phase = m_phase.group(1).strip()
        m = re.match(r"^- \[([ xX])\]\s+(.+)$", line)
        if m:
            items.append((phase, m.group(1).lower() == "x", m.group(2).strip()))
    return items


def _match_rule(item_text: str) -> Optional[EvidenceSpec]:
    for needle, spec in EVIDENCE_RULES:
        if needle in item_text:
            return spec
    return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _artifact_ok(path: Path, schema: Dict[str, Any], max_age_hours: Optional[float]) -> Tuple[bool, str]:
    if not path.is_file():
        return False, "missing artifact"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"invalid json: {exc}"

    if schema.get("require_status"):
        status = str(data.get("status", "")).upper()
        passed = data.get("passed") is True
        if status not in ("PASS", "OK", "SUCCESS") and not passed:
            return False, f"status={data.get('status')}"

    for key in schema.get("require_keys") or []:
        if key not in data:
            return False, f"missing key {key}"

    if schema.get("min_sample_size"):
        size = int(data.get("sample_size") or (data.get("completeness") or {}).get("total") or 0)
        if size < int(schema["min_sample_size"]):
            return False, f"sample_size={size} < {schema['min_sample_size']}"

    if schema.get("require_open_critical_high_zero"):
        if int(data.get("open_critical_high") or 0) != 0:
            return False, f"open_critical_high={data.get('open_critical_high')}"

    if schema.get("require_nas_certified"):
        results = data.get("results") or []
        nas = next((r for r in results if r.get("connector_type") == "nas_smb"), None)
        if not nas or not nas.get("certified"):
            return False, "nas_smb not certified"

    if schema.get("pilot_require_ragflow_engine"):
        engine = str(data.get("parse_engine") or "").lower()
        if "ragflow" not in engine and "deepdoc" not in engine:
            return False, f"parse_engine not ragflow: {data.get('parse_engine')!r}"

    if "get_after_revoke" in schema:
        if data.get("get_after_revoke") != schema["get_after_revoke"]:
            return False, f"get_after_revoke={data.get('get_after_revoke')}"

    if "search_leak_after_max" in schema:
        leak = data.get("search_leak_after")
        if leak is None or int(leak) > int(schema["search_leak_after_max"]):
            return False, f"search_leak_after={leak}"

    for bad in schema.get("forbid_modes") or []:
        if data.get("mode") == bad:
            return False, f"forbidden mode={bad}"

    if max_age_hours is not None:
        ts = _parse_ts(data.get("generated_at") or data.get("finished_at") or data.get("started_at"))
        if ts is None:
            return False, "missing timestamp for freshness"
        age_h = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() / 3600
        if age_h > max_age_hours:
            return False, f"stale artifact age_h={age_h:.1f}"

    return True, "ok"


def _compose_ok(path: Path) -> Tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    # Include overlay files referenced by `include:` so sidecars.yml expose:
    # counts toward the Phase-1 "downstream ports internal-only" evidence.
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = line.strip()
        if m.startswith("- path:"):
            rel = m.split(":", 1)[1].strip().strip("'\"")
            inc = (path.parent / rel).resolve()
            if inc.is_file():
                text += "\n" + inc.read_text(encoding="utf-8")
    checks = [
        ("expose:" in text, "missing expose"),
        ("RAGFLOW_ENABLED" in text, "missing RAGFLOW_ENABLED"),
        ("PIPESHUB_ENABLED" in text, "missing PIPESHUB_ENABLED"),
        ("WEKNORA_ENABLED" in text, "missing WEKNORA_ENABLED"),
        ("worker-beat" in text, "missing worker-beat"),
    ]
    fails = [msg for ok, msg in checks if not ok]
    return (not fails), (", ".join(fails) if fails else "ok")


def _run_pytest(nodeids: Tuple[str, ...]) -> Tuple[bool, str]:
    if not nodeids:
        return False, "no nodeids"
    cmd = [sys.executable, "-m", "pytest", *nodeids, "-q", "--tb=line"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-400:]
    return proc.returncode == 0, f"rc={proc.returncode} {tail}"


# E4 — capability-value gates from CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md
# Each entry: (gate_id, artifact relative path, required top-level keys)
CAPABILITY_VALUE_GATES: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("CV-RF-01a", "artifacts/coverage_ablation_last_run.json", ("gate", "status", "summary")),
    ("CV-RF-01b", "artifacts/parse_ablation_last_run.json", ("gate", "status", "summary")),
    ("CV-PH-03", "artifacts/pipeshub_acl_live_last_run.json", ("status",)),
    ("CV-WK-03", "artifacts/wiki_live_compile_last_run.json", ("status",)),
    ("CV-WK-06", "artifacts/wiki_revoke_recompile_last_run.json", ("gate", "status")),
    ("E1", "artifacts/retrieval_ablation_last_run.json", ("gate", "summary", "judgements")),
    ("CV-WK-04", "artifacts/parent_child_ablation_last_run.json", ("gate", "judgement")),
    ("CV-RF-04", "artifacts/raptor_ablation_last_run.json", ("gate", "judgement")),
    ("CV-RF-05", "artifacts/ragflow_graph_ablation_last_run.json", ("gate", "judgement")),
    ("CV-RF-06", "artifacts/specialist_retrieval_last_run.json", ("gate", "status")),
    ("CV-WK-02", "artifacts/retrieval_ablation_weknora_last_run.json", ("gate", "status")),
    ("CV-WK-05", "artifacts/weknora_graph_ablation_last_run.json", ("gate", "status")),
    ("CV-PH-04", "artifacts/pipeshub_sync_lag_last_run.json", ("gate", "status")),
    ("E2", "artifacts/capability_fanout_decision.json", ("gate", "decision")),
    ("ADR-007", "docs/adr/ADR-007-graph-store-boundary.md", ()),
]


def _evaluate_capability_value_gates(
    max_age_hours: Optional[float],
) -> Dict[str, Any]:
    """Inspect capability-value artifacts; do not invent PASS."""
    items = []
    for gate_id, rel, keys in CAPABILITY_VALUE_GATES:
        path = ROOT / rel
        if rel.endswith(".md"):
            ok = path.is_file()
            items.append({
                "gate": gate_id,
                "artifact": rel,
                "present": ok,
                "status": "PRESENT" if ok else "MISSING",
                "detail": "adr file" if ok else "missing",
            })
            continue
        schema = {"require_keys": list(keys)} if keys else {}
        ok, detail = _artifact_ok(path, schema, max_age_hours)
        gate_status = None
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                gate_status = (
                    payload.get("status")
                    or (payload.get("judgement") or {}).get("judgement")
                    or (payload.get("hit_judgement") or {}).get("judgement")
                    or (payload.get("answerable_only") or {}).get("judgement", {}).get("judgement")
                )
            except Exception as exc:
                detail = f"json error: {exc}"
                ok = False
        items.append({
            "gate": gate_id,
            "artifact": rel,
            "present": path.is_file(),
            "schema_ok": ok,
            "status": gate_status or ("MISSING" if not path.is_file() else "UNKNOWN"),
            "detail": detail,
        })
    present = sum(1 for i in items if i.get("present"))
    return {
        "source": "docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md",
        "total": len(items),
        "present": present,
        "items": items,
    }


def evaluate(
    *,
    run_pytest: bool = False,
    max_age_hours: Optional[float] = None,
) -> Dict[str, Any]:
    plan_text = PLAN.read_text(encoding="utf-8")
    parsed = _parse_checkboxes(plan_text)
    gates: List[GateItem] = []
    pytest_cache: Dict[Tuple[str, ...], Tuple[bool, str]] = {}

    for phase, checked, text in parsed:
        spec = _match_rule(text)
        if not spec:
            gates.append(GateItem(phase, text, checked, None, "no auto rule", "mixed"))
            continue

        path = ROOT / spec.rel
        detail = ""
        ok: Optional[bool]

        if spec.kind == "human":
            ok = None
            detail = "human gate"
        elif spec.kind == "template":
            ok = path.is_file()
            detail = "template/file present (not runtime proof)"
            # templates do not count as verified code
        elif spec.kind == "compose":
            ok, detail = _compose_ok(path)
        elif spec.kind == "artifact":
            ok, detail = _artifact_ok(path, spec.schema, max_age_hours)
        elif spec.kind == "pytest":
            if run_pytest and spec.pytest_nodeids:
                key = spec.pytest_nodeids
                if key not in pytest_cache:
                    pytest_cache[key] = _run_pytest(key)
                ok, detail = pytest_cache[key]
            else:
                ok = path.is_file()
                detail = "test file present (pass --run-pytest to execute)"
        else:  # file
            ok = path.is_file()
            detail = "file present" if ok else "missing"

        gates.append(GateItem(
            phase, text, checked, ok,
            f"{spec.rel} ({spec.note})",
            spec.category if spec.kind != "template" else "template",
            detail=detail,
        ))

    # Verified code = category code with evidence_ok True, excluding templates
    code_items = [g for g in gates if g.category == "code" and g.evidence_ok is not None]
    code_ok = sum(1 for g in code_items if g.evidence_ok)
    code_total = len(code_items)
    checked = sum(1 for g in gates if g.checked_in_plan)
    human = [g for g in gates if g.category == "human"]

    drift_false_green = [g for g in gates if g.checked_in_plan and g.evidence_ok is False]
    drift_under_claimed = [g for g in code_items if (not g.checked_in_plan) and g.evidence_ok]

    status = "PASS" if not drift_false_green else "DRIFT"
    # If many code items fail, surface FAIL for strict consumers
    if code_total and code_ok / code_total < 0.5:
        status = "FAIL"

    capability_value_gates = _evaluate_capability_value_gates(max_age_hours)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan": str(PLAN),
        "mode": {
            "run_pytest": run_pytest,
            "max_age_hours": max_age_hours,
            "note": "code_completion_pct 僅計 category=code；template/mixed/human 另列",
        },
        "totals": {
            "checkboxes": len(gates),
            "checked_in_plan": checked,
            "code_evidence_ok": code_ok,
            "code_evidence_total": code_total,
            "code_completion_pct": round(100.0 * code_ok / code_total, 1) if code_total else 0,
            "human_gates": len(human),
            "template_or_mixed": sum(1 for g in gates if g.category in ("template", "mixed")),
        },
        "drift_false_green": [
            {"phase": g.phase, "text": g.text, "evidence": g.evidence, "detail": g.detail}
            for g in drift_false_green
        ],
        "ready_to_check": [
            {"phase": g.phase, "text": g.text, "evidence": g.evidence}
            for g in drift_under_claimed
        ],
        "gates": [asdict(g) for g in gates],
        "capability_value_gates": capability_value_gates,
        "status": status,
    }


def write_md(report: Dict[str, Any]) -> None:
    t = report["totals"]
    lines = [
        "# Enclave 計畫進度看板",
        "",
        f"自動產生於 `{report['generated_at']}`（嚴格閘門；來源：`DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`）。",
        "",
        f"- 計畫 checkbox：{t['checked_in_plan']}/{t['checkboxes']}",
        f"- **可驗證程式完成率：{t['code_completion_pct']}%**（{t['code_evidence_ok']}/{t['code_evidence_total']}，僅 category=code）",
        f"- template/mixed：{t['template_or_mixed']}；人工閘門：{t['human_gates']}",
        f"- 閘門狀態：`{report['status']}`",
        f"- 模式：`run_pytest={report['mode']['run_pytest']}` `max_age_hours={report['mode']['max_age_hours']}`",
        "",
        "## 假綠（計畫已勾但證據不足）",
        "",
    ]
    if report["drift_false_green"]:
        for item in report["drift_false_green"]:
            lines.append(
                f"- [{item['phase']}] {item['text']} — `{item['evidence']}` "
                f"({item.get('detail', '')})"
            )
    else:
        lines.append("- （無）")
    lines += ["", "## 全部出口條件", "", "| Phase | Plan | Evidence | Cat | Detail | Item |", "|---|---|---|---|---|---|"]
    for g in report["gates"]:
        plan = "x" if g["checked_in_plan"] else " "
        ev = {True: "OK", False: "MISS", None: "—"}.get(g["evidence_ok"], "—")
        lines.append(
            f"| {g['phase'][:32]} | [{plan}] | {ev} | {g['category']} | "
            f"{(g.get('detail') or '')[:40]} | {g['text'][:60]} |"
        )
    lines += [
        "",
        "## 施工指令",
        "",
        "```bash",
        "python scripts/plan_progress_gate.py --write-md --strict",
        "python scripts/plan_progress_gate.py --run-pytest --max-age-hours 168 --write-md --strict",
        "python -m pytest tests/test_p0_production_fixes.py tests/test_plan_phase_gates.py -q",
        "```",
        "",
    ]
    PROGRESS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-md", action="store_true")
    parser.add_argument("--run-pytest", action="store_true", help="實際執行對應 pytest nodeid")
    parser.add_argument("--max-age-hours", type=float, default=None, help="artifact 新鮮度上限")
    parser.add_argument("--strict", action="store_true", help="DRIFT/FAIL 回傳非 0")
    args = parser.parse_args()
    report = evaluate(run_pytest=args.run_pytest, max_age_hours=args.max_age_hours)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_md:
        write_md(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        t = report["totals"]
        print(
            f"plan_progress status={report['status']} "
            f"code={t['code_completion_pct']}% "
            f"({t['code_evidence_ok']}/{t['code_evidence_total']}) "
            f"checked={t['checked_in_plan']}/{t['checkboxes']} "
            f"false_green={len(report['drift_false_green'])}"
        )
    if args.strict:
        return 0 if report["status"] == "PASS" else 1
    return 0 if report["status"] in ("PASS", "DRIFT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
