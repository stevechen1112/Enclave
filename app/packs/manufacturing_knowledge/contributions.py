"""Pure manufacturing ontology and SOP applicability rules."""
from __future__ import annotations

MANUFACTURING_ONTOLOGY = (
    "equipment_model", "procedure_step", "process_parameter", "anomaly", "safety_constraint"
)
MANUFACTURING_DOCUMENT_FAMILIES = ("approved_sop", "work_instruction", "safety_bulletin")
MANUFACTURING_RENDERER_VOCABULARY = {"procedure": "作業步驟", "constraint": "安全限制"}


def project(payload):
    return {"domain": "manufacturing", "allowed_kinds": MANUFACTURING_ONTOLOGY, "payload": dict(payload)}


def compile_requirements(intent):
    return tuple(key for key in ("equipment_model", "procedure_step", "safety_constraint") if key in str(intent))


def aliases(tenant_id: str, term: str):
    # Reference vocabulary is global; customer aliases are supplied to core via
    # a separate tenant-scoped overlay and never cached here.
    del tenant_id
    table = {"sop": ("standard_operating_procedure", "標準作業程序")}
    return table.get(term.casefold(), ())


def applicability(context):
    return all(key in context for key in ("equipment_model", "sop_effective_at", "approval_state"))


def resolve(query):
    return {"document_families": MANUFACTURING_DOCUMENT_FAMILIES, "query": str(query)}


def render_vocabulary(shape: str):
    return MANUFACTURING_RENDERER_VOCABULARY.get(shape, shape)


def invariants():
    return ("manufacturing.model_match_required", "manufacturing.high_risk_formal_sop_only")
