#!/usr/bin/env python3
"""Freeze the KQ0 Knowledge Answer Reliability baseline without live mutations.

This tool is deliberately offline. It records the current source/worktree, API
contracts, static call graph, deterministic fallback behavior, known gaps, and
core-contamination scan. Production identity is copied only from existing
read-only evidence and is explicitly marked historical until an operator
provides a fresh snapshot.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import tokenize
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "knowledge"
sys.path.insert(0, str(ROOT))

RUNTIME_INPUTS = (
    "app/api/v1/endpoints/chat.py",
    "app/schemas/chat.py",
    "app/services/chat_orchestrator.py",
    "app/services/multi_step_orchestrator.py",
    "app/services/query_plan.py",
    "app/services/retrieval_facade.py",
    "app/services/retrieval_coverage.py",
    "app/services/evidence_contract.py",
    "app/services/evidence_orchestrator.py",
    "app/services/source_verifier.py",
    "app/services/knowledge_authority_read.py",
    "app/models/knowledge_unit.py",
    "app/platform/packs/contracts.py",
)

KQ0_TOOLING_INPUTS = (
    "docs/KNOWLEDGE_ANSWER_RELIABILITY_TASK_PLAN_2026-09-03.md",
    "docs/adr/ADR-022-aihr-enclave-knowledge-decision-mapping.md",
    "docs/knowledge/KQ_BASELINE.md",
    "docs/knowledge/KQ_CAPABILITY_DISPOSITION.md",
    "docs/knowledge/PHASE_KQ0_CODE_REVIEW_2026-09-03.md",
    "scripts/freeze_knowledge_answer_baseline.py",
    "tests/test_knowledge_answer_kq0.py",
)

CORE_DIRS = (
    ROOT / "app" / "services",
    ROOT / "app" / "api",
    ROOT / "app" / "agent",
    ROOT / "app" / "gateway",
    ROOT / "app" / "platform",
)

FIXED_CLIENT_TERMS = ("優利", "八策", "金正昌", "杏壺", "味特", "周秀蘭")
CASE_ID = re.compile(r"\b(?:Blind\s*)?Z[1-9]\d*[-_]\d{2,}\b|\breal-\d{3,}\b", re.I)
AIHR_RUNTIME = re.compile(r"\bhr_pv_t0_[A-Za-z0-9_]*\b", re.I)

# This legacy file is already isolated by the HR compatibility flag and has a
# separately documented retirement condition. KQ0 records, rather than hides,
# the waiver; KQ1+ may not add new waivers.
FILE_WAIVERS = {
    "app/services/structured_answers.py": {
        "waiver_id": "KQ0-WAIVER-LEGACY-HR-001",
        "reason": "existing HR compatibility debt; excluded from generic core execution when the flag is off",
        "owner": "Knowledge/RAG backend",
        "retirement_gate": "generic resolver parity and removal of the core direct path",
    }
}

CALL_GRAPH_SPEC = (
    ("POST /chat/stream", "crud_chat.create_message(user)", "app/api/v1/endpoints/chat.py", "user_message = crud_chat.create_message"),
    ("POST /chat/stream", "ChatOrchestrator.retrieve_context", "app/api/v1/endpoints/chat.py", "ctx = await orchestrator.retrieve_context"),
    ("POST /chat/stream", "ChatOrchestrator.stream_answer", "app/api/v1/endpoints/chat.py", "async for chunk in orchestrator.stream_answer"),
    ("POST /chat/stream", "crud_chat.create_message(assistant)", "app/api/v1/endpoints/chat.py", "assistant_message = crud_chat.create_message"),
    ("POST /chat/stream", "crud_chat.create_retrieval_trace", "app/api/v1/endpoints/chat.py", "crud_chat.create_retrieval_trace"),
    ("POST /chat", "ChatOrchestrator.process_query", "app/api/v1/endpoints/chat.py", "result = await orchestrator.process_query"),
    ("POST /chat", "crud_chat.create_message", "app/api/v1/endpoints/chat.py", "crud_chat.create_message"),
    ("POST /chat", "crud_chat.create_retrieval_trace", "app/api/v1/endpoints/chat.py", "crud_chat.create_retrieval_trace"),
    ("ChatOrchestrator.process_query", "HR compatibility resolve (flagged)", "app/services/chat_orchestrator.py", "resolve_hr_compatibility"),
    ("ChatOrchestrator.process_query", "ChatOrchestrator.retrieve_context", "app/services/chat_orchestrator.py", "ctx = await self.retrieve_context"),
    ("ChatOrchestrator.retrieve_context", "MultiStepOrchestrator.run", "app/services/chat_orchestrator.py", "orch_result = await MultiStepOrchestrator().run"),
    ("MultiStepOrchestrator.run", "build_query_plan", "app/services/multi_step_orchestrator.py", "plan = plan or build_query_plan(question)"),
    ("MultiStepOrchestrator.run", "RetrievalFacade", "app/services/multi_step_orchestrator.py", "facade = get_retrieval_facade()"),
    ("ChatOrchestrator._build_context", "assess_retrieval_coverage", "app/services/chat_orchestrator.py", "context[\"evidence_contract\"] = assess_retrieval_coverage"),
    ("ChatOrchestrator.stream_answer", "SourceVerifier (shadow/enforce only)", "app/services/chat_orchestrator.py", "result = await self._run_source_verification"),
)

KNOWN_FAILURES = (
    {
        "id": "KQ0-KF-001",
        "severity": "critical-architecture",
        "summary": "Live Ask does not consume EvidenceOrchestrator as its final decision owner.",
        "evidence": ["app/services/chat_orchestrator.py", "app/services/evidence_orchestrator.py"],
        "target_phase": "KQ2",
    },
    {
        "id": "KQ0-KF-002",
        "severity": "high",
        "summary": "Legacy retrieval coverage uses a small keyword/regex slot table.",
        "evidence": ["app/services/retrieval_coverage.py"],
        "target_phase": "KQ1/KQ2",
    },
    {
        "id": "KQ0-KF-003",
        "severity": "high",
        "summary": "EvidenceContract does not yet enforce value type, source scope, temporal scope, exact KB revision, expected cardinality, or relation closure.",
        "evidence": ["app/services/evidence_contract.py"],
        "target_phase": "KQ1",
    },
    {
        "id": "KQ0-KF-004",
        "severity": "high",
        "summary": "Provider/schema/timeout failures can collapse into an absent/abstain-shaped result because execution status is not orthogonal.",
        "evidence": ["app/services/chat_orchestrator.py", "app/services/retrieval_coverage.py"],
        "target_phase": "KQ1",
    },
    {
        "id": "KQ0-KF-005",
        "severity": "high",
        "summary": "Conflict, entity, source-scope, and exact-revision admission are not owned by the legacy coverage decision.",
        "evidence": ["app/services/retrieval_coverage.py"],
        "target_phase": "KQ2",
    },
    {
        "id": "KQ0-KF-006",
        "severity": "medium",
        "summary": "The synchronous Ask path does not invoke SourceVerifier; stream verification depends on mode.",
        "evidence": ["app/api/v1/endpoints/chat.py", "app/services/chat_orchestrator.py"],
        "target_phase": "KQ2/KQ5",
    },
    {
        "id": "KQ0-KF-007",
        "severity": "medium",
        "summary": "Post-generation verification can reject unsupported claims but cannot recover omitted required facets.",
        "evidence": ["app/services/source_verifier.py"],
        "target_phase": "KQ5",
    },
    {
        "id": "KQ0-KF-008",
        "severity": "high",
        "summary": "Closed-list, per-entity comparison, and relation completeness are not represented in the live decision.",
        "evidence": ["app/services/query_plan.py", "app/services/retrieval_coverage.py"],
        "target_phase": "KQ1/KQ2/KQ4",
    },
    {
        "id": "KQ0-KF-009",
        "severity": "medium",
        "summary": "Multi-turn query rewriting can fail open to the latest short question and does not produce a server-owned ambiguity state.",
        "evidence": ["app/services/chat_orchestrator.py", "app/services/query_plan.py"],
        "target_phase": "KQ1/KQ2",
    },
    {
        "id": "KQ0-KF-010",
        "severity": "medium",
        "summary": "User-visible answer states do not yet distinguish partial, insufficient context, conflict, absent, and execution failure as first-class UI states.",
        "evidence": ["app/schemas/chat.py", "app/api/v1/endpoints/chat.py"],
        "target_phase": "KQ5",
    },
    {
        "id": "KQ0-KF-011",
        "severity": "architecture-debt",
        "summary": "The flagged HR compatibility path can return before the canonical retrieval/evidence path.",
        "evidence": ["app/services/chat_orchestrator.py", "app/services/structured_answers.py"],
        "target_phase": "KQ6 retirement verification",
    },
)

BASELINE_CASES = (
    {
        "case_id": "KQ0-direct-fact",
        "category": "direct_fact",
        "question": "《設備手冊.pdf》的版本是什麼？",
        "results": [{"content": "文件版本 Rev. 3", "metadata": {}}],
        "expected_legacy_decision": "answer",
    },
    {
        "case_id": "KQ0-exhaustive-list",
        "category": "exhaustive_list",
        "question": "列出《設備手冊.pdf》的全部流程步驟。",
        "results": [{"content": "流程步驟：Step 1 檢查；Step 2 啟動。", "metadata": {"evidence_kind": "procedure", "procedure_status": "complete"}}],
        "expected_legacy_decision": "answer",
        "known_gap": "legacy decision does not prove closed-list cardinality",
    },
    {
        "case_id": "KQ0-partial",
        "category": "partial_answer",
        "question": "《報價單.pdf》的單價與交期是什麼？",
        "results": [{"content": "單價：100 元。", "metadata": {}}],
        "expected_legacy_decision": "partial",
    },
    {
        "case_id": "KQ0-absent",
        "category": "absent_answer",
        "question": "《設備手冊.pdf》的交期是什麼？",
        "results": [],
        "expected_legacy_decision": "abstain",
    },
    {
        "case_id": "KQ0-insufficient-context",
        "category": "insufficient_context",
        "question": "這個設備的狀態是什麼？",
        "results": [{"content": "狀態：正常。", "metadata": {}}],
        "expected_legacy_decision": "answer",
        "known_gap": "legacy decision has no distinct clarify/insufficient-context state",
    },
    {
        "case_id": "KQ0-conflict",
        "category": "conflict",
        "question": "《規格甲.pdf》與《規格乙.pdf》的版本差異是什麼？",
        "results": [{"content": "規格甲版本 Rev. 1。", "metadata": {}}, {"content": "規格乙版本 Rev. 2。", "metadata": {}}],
        "expected_legacy_decision": "answer",
        "known_gap": "legacy decision does not issue a conflict state",
    },
    {
        "case_id": "KQ0-comparison",
        "category": "comparison",
        "question": "比較《報價甲.pdf》與《報價乙.pdf》的總價。",
        "results": [{"content": "報價甲總價：100 元。", "metadata": {}}, {"content": "報價乙總價：120 元。", "metadata": {}}],
        "expected_legacy_decision": "answer",
        "known_gap": "legacy decision does not prove per-entity coverage",
    },
    {
        "case_id": "KQ0-procedure",
        "category": "procedure",
        "question": "設備停機流程有哪些步驟？",
        "results": [{"content": "停機流程步驟：Step 1 斷電；Step 2 上鎖。", "metadata": {"evidence_kind": "procedure", "procedure_status": "complete", "authority_level": 95}}],
        "expected_legacy_decision": "answer",
    },
    {
        "case_id": "KQ0-table-same-row",
        "category": "table_same_row",
        "question": "訂單 ORD-001 的單價與交期是什麼？",
        "results": [{"content": "ORD-001 單價：100 元；交期：2026-10-01。", "metadata": {"row_id": "row-1"}}],
        "expected_legacy_decision": "answer",
        "known_gap": "coverage regex itself does not validate same-row identity",
    },
    {
        "case_id": "KQ0-wrong-scope",
        "category": "wrong_scope",
        "question": "《設備手冊.pdf》的版本是什麼？",
        "results": [{"content": "另一份文件版本 Rev. 9。", "metadata": {"document_scope": "other-document"}}],
        "expected_legacy_decision": "answer",
        "known_gap": "legacy decision ignores source scope metadata",
    },
    {
        "case_id": "KQ0-wrong-revision",
        "category": "wrong_revision",
        "question": "《設備手冊.pdf》的版本是什麼？",
        "results": [{"content": "舊版文件版本 Rev. 1。", "metadata": {"active_revision": False}}],
        "expected_legacy_decision": "answer",
        "known_gap": "legacy decision ignores exact revision metadata",
    },
    {
        "case_id": "KQ0-provider-failure",
        "category": "provider_failure",
        "question": "《設備手冊.pdf》的狀態是什麼？",
        "results": [],
        "execution_fixture": {"provider_status": "timeout"},
        "expected_legacy_decision": "abstain",
        "known_gap": "provider timeout collapses to an absent-shaped legacy result",
    },
    {
        "case_id": "KQ0-multi-turn",
        "category": "multi_turn",
        "question": "那交期呢？",
        "history": [{"role": "user", "content": "請查訂單 ORD-001。"}],
        "results": [{"content": "交期：2026-10-01。", "metadata": {}}],
        "expected_legacy_decision": "answer",
        "known_gap": "build_query_plan does not receive history or bind the carried entity",
    },
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _file_record(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    body = path.read_bytes()
    return {"path": relative_path, "bytes": len(body), "sha256": _sha256_bytes(body)}


def source_snapshot() -> dict[str, Any]:
    dirty_entries = sorted(
        line for line in _git("status", "--porcelain=v1", "--untracked-files=normal").splitlines() if line
    )
    records = [_file_record(path) for path in RUNTIME_INPUTS]
    tooling_records = [_file_record(path) for path in KQ0_TOOLING_INPUTS]
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "dirty_entry_count": len(dirty_entries),
        "dirty_manifest_sha256": _sha256_json(dirty_entries),
        "runtime_inputs": records,
        "runtime_inputs_manifest_sha256": _sha256_json(records),
        "kq0_tooling_inputs": tooling_records,
        "kq0_tooling_manifest_sha256": _sha256_json(tooling_records),
    }


def _line_for_anchor(relative_path: str, anchor: str) -> int:
    lines = (ROOT / relative_path).read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, 1):
        if anchor in line:
            return number
    raise ValueError(f"missing call-graph anchor {relative_path}: {anchor}")


def call_graph_snapshot() -> dict[str, Any]:
    edges = [
        {
            "from": source,
            "to": target,
            "source_ref": {"path": path, "line": _line_for_anchor(path, anchor)},
        }
        for source, target, path, anchor in CALL_GRAPH_SPEC
    ]
    return {
        "schema_version": 1,
        "status": "PASS",
        "decision_owners": {
            "live": "app.services.retrieval_coverage.assess_retrieval_coverage",
            "offline_only": "app.services.evidence_orchestrator.decide_evidence",
            "post_generation": "app.services.source_verifier",
        },
        "sync_stream_divergence": [
            "sync calls process_query and does not invoke SourceVerifier",
            "stream calls stream_answer; SourceVerifier runs only in shadow/enforce mode",
            "both paths persist conversation/message/retrieval/usage in normal Live Ask",
        ],
        "edges": edges,
    }


def api_contract_snapshot() -> dict[str, Any]:
    from app.schemas.chat import ChatRequest, ChatResponse

    request_schema = ChatRequest.model_json_schema()
    response_schema = ChatResponse.model_json_schema()
    return {
        "schema_version": 1,
        "sync": {
            "method": "POST",
            "path": "/chat",
            "request_schema": request_schema,
            "response_schema": response_schema,
        },
        "stream": {
            "method": "POST",
            "path": "/chat/stream",
            "media_type": "text/event-stream",
            "request_schema": request_schema,
            "events": {
                "status": {"required": ["type", "content"]},
                "retrieval": {"required": ["type", "retrieval"]},
                "sources": {"required": ["type", "sources"]},
                "token": {"required": ["type", "content"]},
                "suggestions": {"required": ["type", "items"]},
                "done": {"required": ["type", "message_id", "conversation_id"]},
                "error": {"required": ["type", "content"]},
            },
        },
        "contract_sha256": _sha256_json(
            {"request": request_schema, "response": response_schema}
        ),
    }


async def _offline_stream(context: dict[str, Any]) -> list[str]:
    from app.services.chat_orchestrator import ChatOrchestrator

    orchestrator = object.__new__(ChatOrchestrator)
    orchestrator._openai_async = None
    return [
        chunk
        async for chunk in orchestrator.stream_answer(
            question=context["question"], context=context, history=None, include_followup=False
        )
    ]


def behavior_snapshot() -> dict[str, Any]:
    from app.services.chat_orchestrator import ChatOrchestrator
    from app.services.query_plan import build_query_plan
    from app.services.retrieval_coverage import assess_retrieval_coverage

    outputs: list[dict[str, Any]] = []
    for case in BASELINE_CASES:
        plan = build_query_plan(case["question"]).to_dict()
        results = list(case.get("results") or [])
        legacy = assess_retrieval_coverage(plan, results)
        if legacy.get("decision") != case["expected_legacy_decision"]:
            raise AssertionError(
                f"{case['case_id']}: expected {case['expected_legacy_decision']}, got {legacy.get('decision')}"
            )
        has_policy = bool(results)
        if legacy.get("decision") == "abstain" and plan.get("requested_slots"):
            has_policy = False
        context = {
            "question": case["question"],
            "has_policy": has_policy,
            "company_policy_raw": (
                {"content": results[0]["content"], "source": "synthetic-kq0-fixture"}
                if results
                else None
            ),
            "context_parts": [item["content"] for item in results],
            "sources": [],
            "retrieval": {"evidence_contract": legacy},
            "evidence_contract": legacy,
            "disclaimer": "KQ0 offline deterministic fixture; not a production answer.",
        }
        sync_fallback = ChatOrchestrator._fallback_answer(context)
        stream_chunks = asyncio.run(_offline_stream(context))
        outputs.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "question": case["question"],
                "history": case.get("history") or [],
                "execution_fixture": case.get("execution_fixture") or {"provider_status": "ok"},
                "query_plan": plan,
                "legacy_decision": legacy,
                "sync_fallback": sync_fallback,
                "stream_chunks": stream_chunks,
                "sync_stream_fallback_equal": sync_fallback == "".join(stream_chunks),
                "known_gap": case.get("known_gap"),
            }
        )
    return {
        "schema_version": 1,
        "harness": "offline deterministic fallback; no DB, provider, conversation, message, usage, cache, or feedback writes",
        "case_count": len(outputs),
        "categories": sorted(item["category"] for item in outputs),
        "cases": outputs,
    }


def _docstring_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not body or not isinstance(body, list):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ranges.append((first.lineno, getattr(first, "end_lineno", first.lineno)))
    return ranges


def _comment_lines(text: str) -> set[int]:
    lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                lines.add(token.start[0])
    except (IndentationError, tokenize.TokenError):
        return set()
    return lines


def _looks_like_full_question(value: str) -> bool:
    normalized = value.strip()
    if len(normalized) < 24 or not normalized.endswith(("?", "？")):
        return False
    cjk_count = sum("\u4e00" <= char <= "\u9fff" for char in normalized)
    return cjk_count >= 8 or len(normalized.split()) >= 5


def contamination_snapshot() -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    waived: list[dict[str, Any]] = []
    files_scanned = 0
    for base in CORE_DIRS:
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            files_scanned += 1
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                findings.append({"path": relative, "line": exc.lineno or 0, "reason": "syntax_error"})
                continue

            waiver = FILE_WAIVERS.get(relative)
            if waiver:
                signals = sorted(
                    {term for term in FIXED_CLIENT_TERMS if term in text}
                    | ({"domain_formula_or_policy"} if any(term in text for term in ("特休", "資遣費", "加班費", "年資")) else set())
                )
                waived.append({"path": relative, "signals": signals, **waiver})
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imported = (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else [str(node.module or "")]
                    )
                    if any(AIHR_RUNTIME.search(value) for value in imported):
                        findings.append({"path": relative, "line": node.lineno, "reason": "aihr_runtime_import"})
                if isinstance(node, (ast.If, ast.IfExp, ast.Match, ast.comprehension)):
                    subject = getattr(node, "test", None) or getattr(node, "subject", None) or node
                    for child in ast.walk(subject):
                        if not (isinstance(child, ast.Constant) and isinstance(child.value, str)):
                            continue
                        value = child.value
                        if AIHR_RUNTIME.search(value):
                            findings.append({"path": relative, "line": child.lineno, "reason": "aihr_runtime_symbol_in_branch"})
                        if CASE_ID.search(value):
                            findings.append({"path": relative, "line": child.lineno, "reason": "evaluation_case_id_in_branch"})
                        if any(term in value for term in FIXED_CLIENT_TERMS):
                            findings.append({"path": relative, "line": child.lineno, "reason": "fixed_client_value_in_branch"})
                        if _looks_like_full_question(value):
                            findings.append({"path": relative, "line": child.lineno, "reason": "full_question_in_branch"})

            comment_lines = _comment_lines(text)
            doc_ranges = _docstring_ranges(tree)
            for line_number, line in enumerate(text.splitlines(), 1):
                signals = [term for term in FIXED_CLIENT_TERMS if term in line]
                signals.extend(match.group(0) for match in CASE_ID.finditer(line))
                if not signals:
                    continue
                is_doc = any(start <= line_number <= end for start, end in doc_ranges)
                if line_number in comment_lines or is_doc:
                    waived.append(
                        {
                            "waiver_id": f"KQ0-WAIVER-NONEXEC-{relative}:{line_number}",
                            "path": relative,
                            "line": line_number,
                            "signals": sorted(set(signals)),
                            "reason": "non-executable regression provenance comment/docstring",
                            "owner": "Knowledge/RAG backend",
                            "retirement_gate": "remove when the associated regression note is no longer needed",
                        }
                    )
                else:
                    findings.append(
                        {"path": relative, "line": line_number, "reason": "client_or_case_signal_in_executable_text", "signals": sorted(set(signals))}
                    )
    return {
        "schema_version": 1,
        "status": "PASS" if not findings else "FAIL",
        "files_scanned": files_scanned,
        "forbidden": {
            "aihr_runtime_pattern": AIHR_RUNTIME.pattern,
            "evaluation_case_pattern": CASE_ID.pattern,
            "fixed_client_terms": list(FIXED_CLIENT_TERMS),
            "full_question_in_runtime_branch": True,
            "new_domain_formula_or_policy_in_generic_core": True,
        },
        "findings": findings,
        "waivers": waived,
    }


def production_identity_snapshot() -> dict[str, Any]:
    operator_path = ARTIFACT_DIR / "KQ_PRODUCTION_OPERATOR_SNAPSHOT.json"
    if operator_path.is_file():
        operator = _read_json(operator_path)
        return {
            "status": "FRESH_READ_ONLY_OPERATOR_SNAPSHOT",
            "evidence_path": operator_path.relative_to(ROOT).as_posix(),
            "evidence_sha256": _sha256_bytes(operator_path.read_bytes()),
            "captured_at": operator.get("captured_at"),
            "release": operator.get("release"),
            "runtime": operator.get("runtime"),
            "images": operator.get("images"),
            "knowledge_identity": operator.get("knowledge_identity"),
            "mutation_sentinel": operator.get("mutation_sentinel"),
            "operator_attestation": operator.get("operator_attestation"),
        }
    baseline_path = ARTIFACT_DIR / "k0_baseline.json"
    deployment_path = ARTIFACT_DIR / "deployment_manifest.json"
    predeploy_path = ARTIFACT_DIR / "predeploy_manifest.json"
    baseline = _read_json(baseline_path)
    deployment = _read_json(deployment_path)
    predeploy = _read_json(predeploy_path)
    return {
        "status": "HISTORICAL_READ_ONLY_EVIDENCE_REQUIRES_FRESH_OPERATOR_SNAPSHOT",
        "production_baseline": {
            "evidence_path": baseline_path.relative_to(ROOT).as_posix(),
            "evidence_sha256": _sha256_bytes(baseline_path.read_bytes()),
            "generated_at": baseline.get("generated_at"),
            "production_corpus_manifest_id": baseline.get("production_corpus_manifest_id"),
            "source": baseline.get("source"),
            "production_runtime": baseline.get("production_runtime"),
        },
        "acceptance_candidate": {
            "evidence_path": deployment_path.relative_to(ROOT).as_posix(),
            "evidence_sha256": _sha256_bytes(deployment_path.read_bytes()),
            "generated_at": deployment.get("generated_at"),
            "deployment_manifest_id": deployment.get("deployment_manifest_id"),
            "candidate_images": deployment.get("candidate_images"),
        },
        "newer_unattested_predeploy_input": {
            "evidence_path": predeploy_path.relative_to(ROOT).as_posix(),
            "evidence_sha256": _sha256_bytes(predeploy_path.read_bytes()),
            "generated_at": predeploy.get("generated_at"),
            "deployment_manifest_id": predeploy.get("deployment_manifest_id"),
            "candidate_images": predeploy.get("candidate_images"),
        },
        "limitations": [
            "No production connection was opened by this KQ0 tool.",
            "The latest production image, KB revision, Knowledge Unit release, and Pack versions remain unverified for 2026-09-03.",
            "Historical evidence cannot satisfy KQ-BL-01 freshness by itself.",
        ],
    }


def _write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    stored = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256_bytes(stored),
        "bytes": len(stored),
    }


def freeze() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    generated_at = datetime.now(timezone.utc).isoformat()
    source = source_snapshot()
    artifacts = {
        "KQ_API_SCHEMA_SNAPSHOT.json": api_contract_snapshot(),
        "KQ_CALL_GRAPH.json": call_graph_snapshot(),
        "KQ_BASELINE_OUTPUTS.json": behavior_snapshot(),
        "KQ_KNOWN_FAILURES.json": {"schema_version": 1, "failures": list(KNOWN_FAILURES)},
        "KQ_CORE_CONTAMINATION_SCAN.json": contamination_snapshot(),
    }
    records = [
        _write_json(ARTIFACT_DIR / name, {"generated_at": generated_at, **payload})
        for name, payload in artifacts.items()
    ]
    required_categories = {
        "direct_fact", "exhaustive_list", "partial_answer", "absent_answer",
        "insufficient_context", "conflict", "comparison", "procedure",
        "table_same_row", "wrong_scope", "wrong_revision", "provider_failure", "multi_turn",
    }
    actual_categories = set(artifacts["KQ_BASELINE_OUTPUTS.json"]["categories"])
    production_identity = production_identity_snapshot()
    fresh_production = production_identity["status"] == "FRESH_READ_ONLY_OPERATOR_SNAPSHOT"
    exact_identity = bool(
        fresh_production
        and production_identity.get("knowledge_identity", {}).get("pack_versions")
        and production_identity.get("mutation_sentinel", {}).get("equal") is True
        and production_identity.get("mutation_sentinel", {}).get("transaction_read_only")
        is True
    )
    gate_checks = [
        {"name": "offline_case_matrix_complete", "status": "PASS" if required_categories <= actual_categories else "FAIL"},
        {"name": "sync_stream_schema_frozen", "status": "PASS"},
        {"name": "call_graph_anchors_resolved", "status": "PASS"},
        {"name": "known_failures_registered", "status": "PASS" if len(KNOWN_FAILURES) >= 1 else "FAIL"},
        {"name": "core_contamination_zero_unwaived", "status": artifacts["KQ_CORE_CONTAMINATION_SCAN.json"]["status"]},
        {"name": "production_snapshot_fresh", "status": "PASS" if fresh_production else "BLOCKED"},
        {"name": "exact_kb_knowledge_release_pack_versions_frozen", "status": "PASS" if exact_identity else "BLOCKED"},
    ]
    gate_passed = all(item["status"] == "PASS" for item in gate_checks)
    manifest = {
        "schema_version": 1,
        "gate": "KQ-BL-01",
        "generated_at": generated_at,
        "status": "PASS TO NEXT PHASE" if gate_passed else "BLOCKED",
        "reason": (
            "fresh read-only production identity, knowledge release state, Pack versions, and mutation=0 are frozen"
            if gate_passed
            else "fresh read-only production release identity requires an authorized operator snapshot"
        ),
        "privacy": "synthetic questions plus source paths, schemas, hashes, IDs, and non-secret runtime metadata; no tenant content",
        "source_snapshot": source,
        "production_identity": production_identity,
        "artifacts": records,
        "gate_checks": gate_checks,
        "next_allowed_action": (
            "start KQ1 contract work"
            if gate_passed
            else "obtain a fresh read-only operator snapshot; do not start KQ1"
        ),
    }
    manifest_record = _write_json(ARTIFACT_DIR / "KQ_BASELINE_MANIFEST.json", manifest)
    return manifest, [*records, manifest_record]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate the generated baseline after freezing")
    args = parser.parse_args()
    manifest, records = freeze()
    if args.check:
        for record in records:
            path = ROOT / record["path"]
            if _sha256_bytes(path.read_bytes()) != record["sha256"]:
                raise SystemExit(f"artifact hash mismatch: {record['path']}")
    print(json.dumps({"status": manifest["status"], "artifacts": [item["path"] for item in records]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
