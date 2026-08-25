"""Deterministic projection of explicit numbered procedures."""
from __future__ import annotations

import hashlib
import re

from app.models.knowledge_engine import ProcedureGraph, ProcedurePhase

STEP = re.compile(r"^\s*(?:步驟\s*)?(\d+)[.、)）:]\s*(.+)$|^\s*Step\s*(\d+)[.、)）:]?\s*(.+)$", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.+)$")


def project_procedure(db, document, text: str) -> int:
    revision = int(document.version or 1)
    if db.query(ProcedureGraph.id).filter(
        ProcedureGraph.document_id == document.id,
        ProcedureGraph.document_revision == revision,
    ).first():
        return 0
    title = document.filename
    steps = []
    for line in (text or "").splitlines():
        heading = HEADING.match(line.strip())
        if heading and not steps:
            title = heading.group(1).strip()
        match = STEP.match(line)
        if not match:
            continue
        sequence = int(match.group(1) or match.group(3))
        instruction = (match.group(2) or match.group(4) or "").strip()
        if instruction:
            steps.append((sequence, instruction))
    if not steps:
        return 0
    steps.sort(key=lambda value: value[0])
    digest = hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()
    graph = ProcedureGraph(
        tenant_id=document.tenant_id,
        document_id=document.id,
        document_revision=revision,
        title=title[:500],
        scope_json={},
        risk_class="safety_critical" if any(token in (text or "") for token in ("工安", "安全", "危險", "停機")) else "normal",
        content_hash=digest,
    )
    db.add(graph); db.flush()
    for index, (sequence, instruction) in enumerate(steps):
        condition = {}
        condition_match = re.search(r"(?:若|如果)(.+?)[，,則]", instruction)
        if condition_match:
            condition = {"raw": condition_match.group(1).strip()}
        db.add(ProcedurePhase(
            tenant_id=document.tenant_id,
            graph_id=graph.id,
            phase_key=f"step-{sequence}",
            sequence=sequence,
            instruction=instruction,
            condition_json=condition,
            required=True,
            completion_criteria="流程完成" if index == len(steps) - 1 else None,
        ))
    db.flush()
    return len(steps)
