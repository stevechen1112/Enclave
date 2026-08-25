"""Revision-bound structured row and procedure retrieval arms.

These readers deliberately operate on the canonical projections instead of
asking an LLM to reconstruct tables or procedure branches from narrative
chunks.  Every candidate document passes the same PEP and KB-revision scope as
the other retrieval arms before any projected value is exposed.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.models.document import Document
from app.models.knowledge_engine import (
    EntityAlias,
    EntityRegistry,
    ProcedureGraph,
    ProcedurePhase,
    StructuredField,
    StructuredRow,
    StructuredTable,
)
from app.services.document_visibility import apply_document_visibility, deny_set_allows
from app.services.document_readiness import ready_revision_pairs


SLOT_ALIASES = {
    "unit_price": ("單價", "unit price", "price"),
    "total_price": ("總價", "總計", "合計", "total price", "total"),
    "amount": ("金額", "價款", "費用", "amount"),
    "date": ("日期", "date"),
    "delivery_date": ("交期", "交貨日", "到貨日", "delivery"),
    "quantity": ("數量", "quantity", "qty"),
    "status": ("狀態", "進度", "status"),
    "revision": ("版本", "版次", "revision", "rev"),
}
STRUCTURED_SLOTS = frozenset(SLOT_ALIASES)
PROCEDURE_SLOTS = frozenset({"steps", "procedure", "actor"})


def _revision_pairs(db, tenant_id: UUID, scope: dict[str, Any]) -> set[tuple[UUID, int]] | None:
    if "kb_revision_ids" not in scope:
        return None
    ids: list[UUID] = []
    for raw in scope.get("kb_revision_ids") or []:
        try:
            ids.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return set()
    return ready_revision_pairs(db, tenant_id=tenant_id, kb_revision_ids=ids)


def _visible_documents(db, authz, scope: dict[str, Any]) -> dict[UUID, Document]:
    pairs = _revision_pairs(db, authz.tenant_id, scope)
    query = apply_document_visibility(
        db.query(Document), authz=authz, db=db, require_completed=pairs is None
    )
    if scope.get("filename"):
        query = query.filter(Document.filename == str(scope["filename"]))
    documents = {row.id: row for row in query.all() if deny_set_allows(row.id, authz=authz)}
    if pairs is not None:
        allowed_ids = {document_id for document_id, _ in pairs}
        documents = {key: value for key, value in documents.items() if key in allowed_ids}
    return documents


def _header_for_slot(headers: list[str], slot: str) -> str | None:
    aliases = SLOT_ALIASES.get(slot, ())
    for header in headers:
        normalized = str(header).casefold().strip()
        if any(alias.casefold() in normalized for alias in aliases):
            return str(header)
    return None


def _identity_matches(question: str, identity: dict[str, Any]) -> bool:
    q = (question or "").casefold()
    values = [str(value).strip().casefold() for value in (identity or {}).values()]
    return any(value and value in q for value in values)


def _entity_values_in_question(db, tenant_id, question: str) -> set[str]:
    """Return identity values from explicitly mentioned canonical entities.

    Only tenant-active entities and approved aliases participate.  Attributes
    remain configuration data, so a new industry can map equipment/customer
    identities without adding product-code conditions here.
    """
    from app.services.entity_registry import normalize_entity

    normalized_question = normalize_entity(question)
    entities = db.query(EntityRegistry).filter(
        EntityRegistry.tenant_id == tenant_id,
        EntityRegistry.status == "active",
    ).all()
    aliases = db.query(EntityAlias).filter(
        EntityAlias.tenant_id == tenant_id,
        EntityAlias.approved.is_(True),
    ).all()
    aliases_by_entity: dict[UUID, list[str]] = {}
    for alias in aliases:
        aliases_by_entity.setdefault(alias.entity_id, []).append(alias.alias_normalized)
    values: set[str] = set()
    for entity in entities:
        names = [
            normalize_entity(entity.canonical_key),
            normalize_entity(entity.display_name),
            *aliases_by_entity.get(entity.id, []),
        ]
        if not any(len(name) >= 2 and name in normalized_question for name in names):
            continue
        configured = [entity.canonical_key, entity.display_name, *(entity.attributes_json or {}).values()]
        values.update(normalize_entity(str(value)) for value in configured if value not in (None, ""))
    return values


def _identity_matches_entity(identity: dict[str, Any], entity_values: set[str]) -> bool:
    if not entity_values:
        return False
    from app.services.entity_registry import normalize_entity
    return any(normalize_entity(str(value)) in entity_values for value in (identity or {}).values() if value)


def _operation(plan) -> str | None:
    operators = set(plan.operators or [])
    for candidate in ("sum", "max", "min", "average"):
        if candidate in operators:
            return candidate
    return None


def _aggregate(rows: list[StructuredRow], field_name: str, operation: str) -> tuple[str, list[str]] | None:
    values: list[tuple[str, Decimal]] = []
    for row in rows:
        field = next((item for item in row.fields if item.field_name == field_name), None)
        try:
            normalized = (field.normalized_value or {}).get("value")
            raw_number = normalized if isinstance(normalized, (int, float)) else field.raw_value
            match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(raw_number or ""))
            if not match:
                return None
            values.append((str(row.id), Decimal(match.group(0).replace(",", ""))))
        except (AttributeError, InvalidOperation, TypeError):
            return None
    if not values:
        return None
    numbers = [value for _, value in values]
    if operation == "sum":
        result = sum(numbers)
    elif operation == "max":
        result = max(numbers)
    elif operation == "min":
        result = min(numbers)
    else:
        result = sum(numbers) / Decimal(len(numbers))
    return str(result), [row_id for row_id, _ in values]


def load_structured_evidence(*, db, authz, question: str, plan, scope: dict[str, Any]) -> list[dict[str, Any]]:
    requested = [slot for slot in (plan.requested_slots or []) if slot in STRUCTURED_SLOTS]
    if not requested:
        return []
    documents = _visible_documents(db, authz, scope)
    pairs = _revision_pairs(db, authz.tenant_id, scope)
    if not documents or pairs == set():
        return []
    tables = db.query(StructuredTable).filter(
        StructuredTable.tenant_id == authz.tenant_id,
        StructuredTable.document_id.in_(list(documents)),
    ).all()
    if pairs is not None:
        tables = [table for table in tables if (table.document_id, table.document_revision) in pairs]

    evidence: list[dict[str, Any]] = []
    operation = _operation(plan)
    for table in tables:
        field_map = {slot: _header_for_slot(list(table.headers or []), slot) for slot in requested}
        field_map = {slot: header for slot, header in field_map.items() if header}
        if not field_map:
            continue
        rows = db.query(StructuredRow).filter(StructuredRow.table_id == table.id).order_by(StructuredRow.row_number).all()
        matched = [row for row in rows if _identity_matches(question, row.identity_json or {})]
        if not matched:
            entity_values = _entity_values_in_question(db, authz.tenant_id, question)
            matched = [row for row in rows if _identity_matches_entity(row.identity_json or {}, entity_values)]
        candidate_rows = matched or rows
        document = documents[table.document_id]

        lines: list[str] = []
        metadata: dict[str, Any] = {
            "worksheet": table.worksheet,
            "document_revision": table.document_revision,
            "evidence_kind": "structured_row",
            "covered_slots": list(field_map),
            "authority_level": 100,
        }
        if operation:
            if len(field_map) != 1:
                continue
            slot, header = next(iter(field_map.items()))
            calculated = _aggregate(candidate_rows, header, operation)
            if calculated is None:
                continue
            value, row_ids = calculated
            lines.append(f"{operation}（{header}）＝{value}")
            metadata.update({"field_name": header, "row_ids": row_ids, "derivation": operation, "slot": slot})
        else:
            # Values may only be combined when one exact physical row has been
            # selected.  A multi-row match/absence is ambiguity, not evidence.
            if len(candidate_rows) != 1:
                evidence.append({
                    "id": f"structured-ambiguity:{table.id}",
                    "content": "【結構化資料】資料列不唯一；必須補充可唯一識別資料列的名稱、編號或代號。",
                    "score": 1.3,
                    "document_id": str(document.id),
                    "document_revision": table.document_revision,
                    "filename": document.filename,
                    "source": "structured_projection",
                    "metadata": {
                        **metadata,
                        "evidence_kind": "structured_ambiguity",
                        "candidate_row_ids": [str(row.id) for row in candidate_rows],
                    },
                    "citations": [],
                })
                continue
            row = candidate_rows[0]
            fields = {field.field_name: field for field in row.fields}
            for slot, header in field_map.items():
                field = fields.get(header)
                if field is not None and field.raw_value not in (None, ""):
                    lines.append(f"{header}：{field.raw_value}")
            if not lines:
                continue
            identity = "、".join(f"{key}：{value}" for key, value in (row.identity_json or {}).items())
            if identity:
                lines.insert(0, f"列識別：{identity}")
            metadata.update({"row_id": str(row.id), "row_number": row.row_number})

        evidence.append({
            "id": f"structured:{table.id}:{metadata.get('row_id') or operation}",
            "content": "【結構化資料】\n" + "\n".join(lines),
            "score": 1.25,
            "document_id": str(document.id),
            "document_revision": table.document_revision,
            "filename": document.filename,
            "source": "structured_projection",
            "metadata": metadata,
            "citations": [],
        })
    return evidence


def load_procedure_evidence(*, db, authz, question: str, plan, scope: dict[str, Any]) -> list[dict[str, Any]]:
    requested = set(plan.requested_slots or []) & PROCEDURE_SLOTS
    if not requested:
        return []
    documents = _visible_documents(db, authz, scope)
    pairs = _revision_pairs(db, authz.tenant_id, scope)
    if not documents or pairs == set():
        return []
    graphs = db.query(ProcedureGraph).filter(
        ProcedureGraph.tenant_id == authz.tenant_id,
        ProcedureGraph.document_id.in_(list(documents)),
    ).all()
    if pairs is not None:
        graphs = [graph for graph in graphs if (graph.document_id, graph.document_revision) in pairs]

    q = (question or "").casefold()

    def relevance(graph: ProcedureGraph) -> int:
        names = [graph.title, documents[graph.document_id].filename.rsplit(".", 1)[0]]
        score = 0
        for name in names:
            core = re.sub(r"(?:標準作業程序|作業程序|作業流程|sop|流程|步驟|程序)", "", name.casefold())
            core = re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", core)
            if core and core in re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", q):
                score = max(score, 100 + len(core))
            bigrams = {core[index:index + 2] for index in range(max(len(core) - 1, 0))}
            score = max(score, len([value for value in bigrams if value in q]))
        return score

    scored = sorted(((relevance(graph), graph) for graph in graphs), key=lambda item: item[0], reverse=True)
    positive = [graph for score, graph in scored if score > 0]
    if not positive and len(graphs) > 1:
        return [{
            "id": "procedure-ambiguity",
            "content": "【作業流程】無法唯一判斷要查詢哪一項流程；請補充流程、設備或作業名稱。",
            "score": 1.3,
            "document_id": None,
            "filename": "",
            "source": "procedure_projection",
            "metadata": {"evidence_kind": "procedure_ambiguity", "candidate_graph_ids": [str(graph.id) for graph in graphs]},
            "citations": [],
        }]
    ranked = (positive or graphs)[:5]
    evidence: list[dict[str, Any]] = []
    for graph in ranked:
        phases = db.query(ProcedurePhase).filter(ProcedurePhase.graph_id == graph.id).order_by(ProcedurePhase.sequence).all()
        selected: list[ProcedurePhase] = []
        unresolved: list[ProcedurePhase] = []
        for phase in phases:
            raw = str((phase.condition_json or {}).get("raw") or "").strip()
            if raw and raw.casefold() not in q:
                unresolved.append(phase)
            else:
                selected.append(phase)
        if not selected:
            continue
        lines = []
        for phase in selected:
            actor = f"（負責：{phase.actor}）" if phase.actor else ""
            completion = f"；完成條件：{phase.completion_criteria}" if phase.completion_criteria else ""
            lines.append(f"{phase.sequence}. {phase.instruction}{actor}{completion}")
        status = "partial" if unresolved else "complete"
        if unresolved:
            conditions = "、".join(str((phase.condition_json or {}).get("raw")) for phase in unresolved)
            lines.append(f"尚需確認適用條件：{conditions}；未確認前不得自行選擇分支。")
        document = documents[graph.document_id]
        evidence.append({
            "id": f"procedure:{graph.id}",
            "content": f"【作業流程：{graph.title}】\n" + "\n".join(lines),
            "score": 1.2 if status == "complete" else 1.1,
            "document_id": str(document.id),
            "document_revision": graph.document_revision,
            "filename": document.filename,
            "source": "procedure_projection",
            "metadata": {
                "evidence_kind": "procedure",
                "procedure_status": status,
                "missing_phase_keys": [phase.phase_key for phase in unresolved],
                "covered_slots": sorted(requested),
                "authority_level": 100,
                "risk_class": graph.risk_class,
            },
            "citations": [],
        })
    return evidence
