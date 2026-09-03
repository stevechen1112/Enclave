"""Pure HR vocabulary/rules. No customer-specific answers or persistence."""
from __future__ import annotations

HR_ONTOLOGY = ("policy", "benefit", "leave_rule", "eligibility", "calculation_rule")
HR_DOCUMENT_FAMILIES = ("employee_handbook", "benefit_policy", "leave_policy")
HR_TEMPORAL_RULES = ("effective_period", "employment_status", "jurisdiction")
HR_RENDERER_VOCABULARY = {"procedure": "申請步驟", "eligibility": "適用資格"}


def project(payload):
    return {"domain": "hr", "allowed_kinds": HR_ONTOLOGY, "payload": dict(payload)}


def compile_requirements(intent):
    return tuple(key for key in ("policy", "eligibility", "effective_period") if key in str(intent))


def aliases(tenant_id: str, term: str):
    del tenant_id
    table = {"pto": ("paid_time_off", "特別休假"), "特休": ("paid_time_off",)}
    return table.get(term.casefold(), ())


def applicability(context):
    return all(key in context for key in ("effective_at", "employment_status"))


def resolve(query):
    return {"document_families": HR_DOCUMENT_FAMILIES, "query": str(query)}


def render_vocabulary(shape: str):
    return HR_RENDERER_VOCABULARY.get(shape, shape)


def invariants():
    return ("hr.effective_period_required", "hr.employment_status_required")
